const $=(selector,root=document)=>root.querySelector(selector);
const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];
const state={token:sessionStorage.getItem('g-one-token')||'',setupRequired:null,me:null,devices:[],support:[],audit:[],vpn:null,peers:[],workspace:null,users:[],tokens:[],roles:[]};
const labels={overview:'개요',workspace:'워크스페이스 관리',users:'사용자 관리',tokens:'토큰 관리',roles:'권한 관리',devices:'장치',vpn:'WireGuard 관리',support:'원격 지원',audit:'감사 로그'};

class ApiError extends Error{constructor(message,status){super(message);this.status=status;}}
async function api(path,options={}){
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(state.token) headers.Authorization=`Bearer ${state.token}`;
  const response=await fetch(path,{...options,headers});
  if(response.status===204)return null;
  const data=await response.json().catch(()=>({detail:'서버 응답을 읽을 수 없습니다.'}));
  if(!response.ok)throw new ApiError(typeof data.detail==='string'?data.detail:'요청을 처리하지 못했습니다.',response.status);
  return data;
}
function escapeHtml(value){return String(value).replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));}
function date(value){return new Intl.DateTimeFormat('ko-KR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value));}
function statusLabel(value){return {registered:'등록됨',revoked:'회수됨',pending:'대기 중',accepted:'진행 중',denied:'거절됨',ended:'종료됨',expired:'만료됨'}[value]||value;}
function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2800);}
function showError(error){const el=$('#globalError');el.textContent=error.message;el.classList.remove('hidden');}
function setBusy(button,busy,label='처리 중…'){if(busy){button.dataset.label=button.innerHTML;button.textContent=label;button.disabled=true;}else{button.innerHTML=button.dataset.label||button.innerHTML;button.disabled=false;}}
function empty(message){return `<div class="empty">${escapeHtml(message)}</div>`;}
function deviceRows(items){return items.length?items.map(d=>`<div class="list-row"><span class="item-icon">▣</span><div><strong>${escapeHtml(d.name)}</strong><small>${escapeHtml(d.owner_id)} · ${date(d.created_at)}</small></div><span class="status ${d.status}">${statusLabel(d.status)}</span></div>`).join(''):empty('등록된 장치가 없습니다.');}
function supportRows(items){return items.length?items.map(r=>`<div class="list-row"><span class="item-icon">◎</span><div><strong>${escapeHtml(r.purpose)}</strong><small>${escapeHtml(deviceName(r.target_device_id))} · ${date(r.created_at)}</small></div><span class="status ${r.state}">${statusLabel(r.state)}</span></div>`).join(''):empty('지원 요청이 없습니다.');}
function deviceName(id){return state.devices.find(d=>d.id===id)?.name||id.slice(0,8);}

async function loadData(){
  $('#globalError').classList.add('hidden');
  try{
    const [devices,support]=await Promise.all([api('/api/v1/devices'),api('/api/v1/support-requests')]);
    state.devices=devices;state.support=support;render();
  }catch(error){showError(error);}
}
function render(){
  const active=state.devices.filter(d=>d.status==='registered');
  $('#deviceCount').textContent=state.devices.length;$('#activeCount').textContent=active.length;
  $('#pendingCount').textContent=state.support.filter(r=>r.state==='pending').length;
  $('#deviceBadge').textContent=state.devices.length;$('#supportBadge').textContent=state.support.filter(r=>r.state==='pending').length;
  $('#deviceTotal').textContent=`${state.devices.length}대`;
  $('#recentDevices').innerHTML=deviceRows(state.devices.slice(0,4));$('#recentSupport').innerHTML=supportRows(state.support.slice(0,4));
  $('#supportDevice').innerHTML=active.map(d=>`<option value="${d.id}">${escapeHtml(d.name)} · ${escapeHtml(d.owner_id)}</option>`).join('');
  renderDeviceTable();
  $('#supportTable').innerHTML=state.support.length?`<table class="data-table"><thead><tr><th>목적</th><th>장치</th><th>요청자</th><th>권한</th><th>상태</th><th>요청일</th></tr></thead><tbody>${state.support.map(r=>`<tr><td><strong>${escapeHtml(r.purpose)}</strong></td><td>${escapeHtml(deviceName(r.target_device_id))}</td><td>${escapeHtml(r.requester_id)}</td><td>${r.permissions.map(escapeHtml).join(', ')}</td><td><span class="status ${r.state}">${statusLabel(r.state)}</span></td><td>${date(r.created_at)}</td></tr>`).join('')}</tbody></table>`:empty('지원 요청이 없습니다.');
}
function renderDeviceTable(){
  const query=$('#deviceSearch').value.trim().toLocaleLowerCase();
  const devices=state.devices.filter(d=>`${d.name} ${d.owner_id} ${d.platform}`.toLocaleLowerCase().includes(query));
  $('#devicesTable').innerHTML=devices.length?`<table class="data-table"><thead><tr><th>장치</th><th>소유자</th><th>플랫폼</th><th>상태</th><th>등록일</th><th></th></tr></thead><tbody>${devices.map(d=>`<tr><td><strong>${escapeHtml(d.name)}</strong></td><td>${escapeHtml(d.owner_id)}</td><td>${escapeHtml(d.platform)}</td><td><span class="status ${d.status}">${statusLabel(d.status)}</span></td><td>${date(d.created_at)}</td><td>${d.status==='registered'?`<button class="danger-btn" data-revoke="${d.id}">접근 회수</button>`:''}</td></tr>`).join('')}</tbody></table>`:empty(query?'검색 결과가 없습니다.':'첫 장치를 등록해 보세요.');
}
async function loadManagement(){
  try{
    [state.workspace,state.users,state.tokens,state.roles]=await Promise.all(['/api/v1/workspace','/api/v1/users','/api/v1/tokens','/api/v1/roles'].map(api));
    $('#workspaceId').value=state.workspace.id;$('#workspaceDisplayName').value=state.workspace.name;
    $('#usersTable').innerHTML=state.users.length?`<table class="data-table"><thead><tr><th>사용자</th><th>역할</th><th>VPN 주소</th><th>라우팅 경로</th><th>정책</th><th>상태</th></tr></thead><tbody>${state.users.map(u=>`<tr><td><strong>${escapeHtml(u.display_name)}</strong><small>${escapeHtml(u.subject)}</small></td><td>${u.roles.map(escapeHtml).join(', ')||'—'}</td><td>${escapeHtml(u.vpn_address||'미지정')}</td><td>${escapeHtml(u.allowed_ips||'미지정')}</td><td>v${u.policy_version}</td><td><span class="status ${u.status==='active'?'registered':'revoked'}">${u.status==='active'?'활성':'중지'}</span></td></tr>`).join('')}</tbody></table>`:empty('등록된 사용자가 없습니다.');
    $('#tokensTable').innerHTML=state.tokens.length?`<table class="data-table"><thead><tr><th>이름</th><th>접두사</th><th>범위</th><th>만료</th><th></th></tr></thead><tbody>${state.tokens.map(t=>`<tr><td><strong>${escapeHtml(t.name)}</strong></td><td><code>${escapeHtml(t.prefix)}…</code></td><td>${t.scopes.map(escapeHtml).join(', ')}</td><td>${date(t.expires_at)}</td><td>${t.revoked_at?'회수됨':`<button class="danger-btn" data-revoke-token="${t.id}">회수</button>`}</td></tr>`).join('')}</tbody></table>`:empty('발급된 토큰이 없습니다.');
    $('#rolesGrid').innerHTML=state.roles.map(r=>`<article><div class="metric-top"><span>${escapeHtml(r.name)}</span><i class="metric-icon purple">◈</i></div><strong>${escapeHtml(r.id)}</strong><small>${r.permissions.map(escapeHtml).join(' · ')}</small></article>`).join('');
  }catch(error){showError(error);}
}
async function loadVpn(){
  try{state.vpn=await api('/api/v1/vpn/network');state.peers=await api('/api/v1/vpn/peers');}
  catch(error){if(error.message==='VPN network not configured'){state.vpn=null;state.peers=[];}else{showError(error);}}
  renderVpn();
}
function renderVpn(){
  $('#vpnBadge').textContent=state.peers.filter(p=>p.enabled).length;$('#peerTotal').textContent=`${state.peers.length}개`;$('#routeTotal').textContent=`${state.peers.filter(p=>p.enabled).length}개 활성`;
  $('#vpnSummary').innerHTML=state.vpn?`<div><p class="kicker">PRIVATE NETWORK</p><h3>${escapeHtml(state.vpn.name)}</h3><p>${escapeHtml(state.vpn.address_cidr)} · ${escapeHtml(state.vpn.endpoint)}:${state.vpn.listen_port}</p></div><div class="vpn-key"><small>서버 공개 키</small><code>${escapeHtml(state.vpn.server_public_key||'서버 개인 키 미설정')}</code><span class="status ${state.vpn.runtime_enabled?'registered':'pending'}">${state.vpn.runtime_enabled?'런타임 적용':'구성 전용'}</span></div>`:empty('서버 설정을 먼저 구성하세요.');
  $('#serverDetails').innerHTML=state.vpn?`<div class="server-detail-grid"><div><small>인터페이스 주소</small><strong>${escapeHtml(state.vpn.address_cidr)}</strong></div><div><small>외부 엔드포인트</small><strong>${escapeHtml(state.vpn.endpoint)}:${state.vpn.listen_port}</strong></div><div><small>클라이언트 DNS</small><strong>${escapeHtml(state.vpn.dns||'시스템 기본값')}</strong></div><div><small>적용 모드</small><strong>${state.vpn.runtime_enabled?'실시간 적용':'구성 전용'}</strong></div></div>`:empty('서버 설정이 없습니다.');
  $('#peersTable').innerHTML=state.peers.length?`<table class="data-table"><thead><tr><th>피어</th><th>VPN 주소</th><th>공개 키</th><th>Keepalive</th><th>상태</th><th></th></tr></thead><tbody>${state.peers.map(p=>`<tr><td><strong>${escapeHtml(p.name)}</strong></td><td>${escapeHtml(p.address)}</td><td><code>${escapeHtml(p.public_key.slice(0,12))}…</code></td><td>${p.persistent_keepalive}초</td><td><span class="status ${p.enabled?'registered':'revoked'}">${p.enabled?'활성':'회수됨'}</span></td><td>${p.enabled?`<button class="danger-btn" data-revoke-peer="${p.id}">접근 회수</button>`:''}</td></tr>`).join('')}</tbody></table>`:empty('등록된 VPN 피어가 없습니다.');
  $('#routesTable').innerHTML=state.peers.length?`<table class="data-table"><thead><tr><th>피어</th><th>터널 주소</th><th>AllowedIPs</th><th>상태</th><th></th></tr></thead><tbody>${state.peers.map(p=>`<tr><td><strong>${escapeHtml(p.name)}</strong></td><td>${escapeHtml(p.address)}</td><td><div class="route-chips">${p.allowed_ips.split(',').map(route=>`<span class="route-chip">${escapeHtml(route.trim())}</span>`).join('')}</div></td><td><span class="status ${p.enabled?'registered':'revoked'}">${p.enabled?'적용':'회수됨'}</span></td><td>${p.enabled?`<button class="route-btn" data-edit-routes="${p.id}">정책 편집</button>`:''}</td></tr>`).join('')}</tbody></table>`:empty('라우팅을 설정할 피어가 없습니다.');
}
async function connect(){
  try{
    state.me=await api('/api/v1/me');sessionStorage.setItem('g-one-token',state.token);
    $('#workspaceName').textContent=state.me.tenant_id;$('#accountName').textContent=state.me.subject;$('#greetingName').textContent=state.me.subject;$('#avatar').textContent=state.me.subject[0].toUpperCase();$('#accountRole').textContent=state.me.roles.join(' · ');
    $('#loginView').classList.add('hidden');$('#appView').classList.remove('hidden');
    try{state.workspace=await api('/api/v1/workspace');$('#workspaceName').textContent=state.workspace.name;await loadData();}
    catch(error){if(error.status!==404)throw error;$('#setupWorkspaceId').value=state.me.tenant_id;$('#setupWorkspaceName').value='';$('#workspaceSetupDialog').showModal();}
  }catch(error){state.token='';sessionStorage.removeItem('g-one-token');$('#loginError').textContent=`연결 실패: ${error.message}`;$('#loginView').classList.remove('hidden');$('#appView').classList.add('hidden');}
}
function go(page){$$('.page').forEach(el=>el.classList.toggle('hidden',el.dataset.view!==page));$$('.nav').forEach(el=>el.classList.toggle('active',el.dataset.page===page));$('#pageTitle').textContent=labels[page];$('#sidebar').classList.remove('open');if(page==='audit')loadAudit();if(page==='vpn')loadVpn();if(['workspace','users','tokens','roles'].includes(page))loadManagement();}
async function loadAudit(){try{state.audit=await api('/api/v1/audit-events');$('#auditTable').innerHTML=state.audit.length?`<table class="data-table"><thead><tr><th>작업</th><th>행위자</th><th>대상</th><th>결과</th><th>시각</th></tr></thead><tbody>${state.audit.map(e=>`<tr><td><strong>${escapeHtml(e.action)}</strong></td><td>${escapeHtml(e.actor_id)}</td><td>${escapeHtml(e.target_type)} · ${escapeHtml(e.target_id.slice(0,8))}</td><td>${escapeHtml(e.outcome)}</td><td>${date(e.occurred_at)}</td></tr>`).join('')}</tbody></table>`:empty('감사 이벤트가 없습니다.');}catch(error){$('#auditTable').innerHTML=empty(`조회할 수 없습니다: ${error.message}`);}}

$('#loginForm').addEventListener('submit',async e=>{e.preventDefault();if(state.setupRequired===null)return;$('#loginError').textContent='';const button=e.submitter;setBusy(button,true,state.setupRequired?'설정하는 중…':'연결하는 중…');try{const body={subject:$('#subject').value,tenant_id:$('#tenant').value,password:$('#consolePassword').value};if(state.setupRequired)body.display_name=$('#displayName').value;const endpoint=state.setupRequired?'/api/v1/setup/administrator':'/api/v1/session/login';const result=await api(endpoint,{method:'POST',body:JSON.stringify(body)});state.setupRequired=false;state.token=result.access_token;await connect();}catch(error){$('#loginError').textContent=`로그인 실패: ${error.message}`;if(error.status===409)await initializeLogin();}finally{setBusy(button,false);}});
$('#tokenToggle').onclick=()=>$('#tokenForm').classList.toggle('hidden');$('#tokenForm').addEventListener('submit',async e=>{e.preventDefault();state.token=$('#accessToken').value.trim();await connect();});
$('#passwordToggle').onclick=()=>{const input=$('#consolePassword');const visible=input.type==='text';input.type=visible?'password':'text';$('#passwordToggle').textContent=visible?'보기':'숨김';$('#passwordToggle').setAttribute('aria-label',visible?'암호 표시':'암호 숨기기');};
$('#logout').onclick=()=>{sessionStorage.removeItem('g-one-token');location.reload();};$('#menuButton').onclick=()=>$('#sidebar').classList.toggle('open');$('#sidebarBackdrop').onclick=()=>$('#sidebar').classList.remove('open');$$('.nav').forEach(el=>el.onclick=()=>go(el.dataset.page));$$('[data-go]').forEach(el=>el.onclick=()=>go(el.dataset.go));
$('#addDevice').onclick=()=>$('#deviceDialog').showModal();$$('[data-action="open-support"]').forEach(el=>el.onclick=()=>{if(!state.devices.some(d=>d.status==='registered'))return toast('먼저 활성 장치를 등록하세요.');$('#supportDialog').showModal();});$$('[data-close]').forEach(el=>el.onclick=()=>el.closest('dialog').close());
$('#deviceForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/v1/devices',{method:'POST',body:JSON.stringify({name:$('#deviceName').value})});e.target.reset();$('#deviceDialog').close();toast('장치를 등록했습니다.');await loadData();}catch(error){showError(error);}});
$('#supportForm').addEventListener('submit',async e=>{e.preventDefault();const permissions=$$('input[name="permission"]:checked').map(el=>el.value);if(!permissions.length)return toast('권한을 하나 이상 선택하세요.');try{await api('/api/v1/support-requests',{method:'POST',body:JSON.stringify({target_device_id:$('#supportDevice').value,purpose:$('#supportPurpose').value,permissions})});e.target.reset();$('#supportDialog').close();toast('지원 요청을 보냈습니다.');await loadData();}catch(error){showError(error);}});
$('#devicesTable').addEventListener('click',async e=>{const id=e.target.dataset.revoke;if(!id||!confirm('이 장치의 접근을 회수할까요?'))return;try{await api(`/api/v1/devices/${id}`,{method:'DELETE'});toast('장치 접근을 회수했습니다.');await loadData();}catch(error){showError(error);}});$('#refreshAudit').onclick=loadAudit;
$('#deviceSearch').addEventListener('input',renderDeviceTable);
$('#addUser').onclick=()=>$('#userDialog').showModal();
$('#addToken').onclick=()=>$('#tokenDialog').showModal();
$('#workspaceForm').addEventListener('submit',async event=>{event.preventDefault();try{await api('/api/v1/workspace',{method:'PUT',body:JSON.stringify({name:$('#workspaceDisplayName').value})});toast('워크스페이스를 저장했습니다.');await loadManagement();}catch(error){showError(error);}});
$('#workspaceSetupForm').addEventListener('submit',async event=>{event.preventDefault();const button=event.submitter;$('#setupError').textContent='';setBusy(button,true,'생성하는 중…');try{state.workspace=await api('/api/v1/workspace',{method:'PUT',body:JSON.stringify({name:$('#setupWorkspaceName').value})});$('#workspaceName').textContent=state.workspace.name;$('#workspaceSetupDialog').close();toast('워크스페이스를 생성했습니다.');await loadData();}catch(error){$('#setupError').textContent=error.message;}finally{setBusy(button,false);}});
$('#userForm').addEventListener('submit',async event=>{event.preventDefault();const roles=$$('input[name="userRole"]:checked').map(el=>el.value);try{await api('/api/v1/users',{method:'POST',body:JSON.stringify({subject:$('#userSubject').value,display_name:$('#userName').value,password:$('#userPassword').value,email:$('#userEmail').value||null,vpn_address:$('#userVpnAddress').value||null,allowed_ips:$('#userAllowedIps').value,roles})});event.target.reset();$('#userDialog').close();toast('사용자를 등록했습니다.');await loadManagement();}catch(error){showError(error);}});
$('#tokenCreateForm').addEventListener('submit',async event=>{event.preventDefault();const scopes=$$('input[name="tokenScope"]:checked').map(el=>el.value);if(!scopes.length)return toast('범위를 하나 이상 선택하세요.');try{const issued=await api('/api/v1/tokens',{method:'POST',body:JSON.stringify({name:$('#tokenName').value,scopes,lifetime_days:Number($('#tokenDays').value)})});event.target.reset();$('#tokenDialog').close();$('#issuedToken').value=issued.token;$('#issuedTokenDialog').showModal();await loadManagement();}catch(error){showError(error);}});
$('#tokensTable').addEventListener('click',async event=>{const id=event.target.dataset.revokeToken;if(!id||!confirm('이 토큰을 즉시 회수할까요?'))return;try{await api(`/api/v1/tokens/${id}`,{method:'DELETE'});toast('토큰을 회수했습니다.');await loadManagement();}catch(error){showError(error);}});
$('#configureVpn').onclick=()=>{if(state.vpn){$('#vpnName').value=state.vpn.name;$('#vpnCidr').value=state.vpn.address_cidr;$('#vpnEndpoint').value=state.vpn.endpoint;$('#vpnPort').value=state.vpn.listen_port;$('#vpnDns').value=state.vpn.dns||'';}$('#vpnDialog').showModal();};
function openPeerDialog(){if(!state.vpn)return toast('먼저 VPN 서버를 설정하세요.');$('#peerAllowedIps').value=state.vpn.network_route;$('#peerDialog').showModal();}
$('#addPeer').onclick=openPeerDialog;$$('[data-add-peer]').forEach(button=>button.onclick=openPeerDialog);$$('[data-edit-server]').forEach(button=>button.onclick=()=>$('#configureVpn').click());
$('#vpnForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/v1/vpn/network',{method:'PUT',body:JSON.stringify({name:$('#vpnName').value,address_cidr:$('#vpnCidr').value,endpoint:$('#vpnEndpoint').value,listen_port:Number($('#vpnPort').value),dns:$('#vpnDns').value||null})});$('#vpnDialog').close();toast('VPN 서버 설정을 저장했습니다.');await loadVpn();}catch(error){showError(error);}});
$('#peerForm').addEventListener('submit',async e=>{e.preventDefault();try{const result=await api('/api/v1/vpn/peers',{method:'POST',body:JSON.stringify({name:$('#peerName').value,address:$('#peerAddress').value,allowed_ips:$('#peerAllowedIps').value,public_key:$('#peerPublicKey').value||null,persistent_keepalive:Number($('#peerKeepalive').value)})});e.target.reset();$('#peerDialog').close();if(result.client_config){$('#clientConfig').value=result.client_config;$('#configDialog').showModal();}else toast('피어를 추가했습니다.');await loadVpn();}catch(error){showError(error);}});
$('#peersTable').addEventListener('click',async e=>{const id=e.target.dataset.revokePeer;if(!id||!confirm('이 피어의 VPN 접근을 회수할까요?'))return;try{await api(`/api/v1/vpn/peers/${id}`,{method:'DELETE'});toast('VPN 접근을 회수했습니다.');await loadVpn();}catch(error){showError(error);}});
$('#copyConfig').onclick=async()=>{await navigator.clipboard.writeText($('#clientConfig').value);toast('클라이언트 설정을 복사했습니다.');};
$$('.vpn-tab').forEach(tab=>tab.onclick=()=>{$$('.vpn-tab').forEach(item=>item.classList.toggle('active',item===tab));$$('.vpn-pane').forEach(pane=>pane.classList.toggle('hidden',pane.dataset.vpnPane!==tab.dataset.vpnTab));});
$('#routesTable').addEventListener('click',event=>{const peer=state.peers.find(item=>item.id===event.target.dataset.editRoutes);if(!peer)return;$('#routePeerId').value=peer.id;$('#routePeerName').textContent=peer.name;$('#routeAllowedIps').value=peer.allowed_ips;$('#routeDialog').showModal();});
$$('[data-route-preset]').forEach(button=>button.onclick=()=>{$('#routeAllowedIps').value=button.dataset.routePreset==='full'?'0.0.0.0/0, ::/0':state.vpn.network_route;});
$('#routeForm').addEventListener('submit',async event=>{event.preventDefault();try{await api(`/api/v1/vpn/peers/${$('#routePeerId').value}/routes`,{method:'PUT',body:JSON.stringify({allowed_ips:$('#routeAllowedIps').value})});$('#routeDialog').close();toast('라우팅 정책을 저장했습니다.');await loadVpn();}catch(error){showError(error);}});
$$('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog&&!dialog.classList.contains('setup-dialog'))dialog.close();}));
$('#workspaceSetupDialog').addEventListener('cancel',event=>event.preventDefault());
document.addEventListener('keydown',event=>{if(event.key==='Escape')$('#sidebar').classList.remove('open');});
$('#currentDate').textContent=new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'long',day:'numeric',weekday:'short'}).format(new Date());
async function initializeLogin(){try{const status=await api('/api/v1/setup/status');state.setupRequired=status.administrator_required;$('#loginTitle').textContent=state.setupRequired?'관리자 계정 설정':'관리 콘솔에 로그인';$('#loginGuide').textContent=state.setupRequired?'최초 관리자 정보를 설정한 뒤 워크스페이스를 생성하세요.':'관리자가 발급한 계정과 워크스페이스 정보를 입력하세요.';$('#displayNameField').classList.toggle('hidden',!state.setupRequired);$('#displayName').required=state.setupRequired;$('#loginSubmit').disabled=false;}catch(error){$('#loginError').textContent=`초기화 상태를 확인하지 못했습니다: ${error.message}`;}}
initializeLogin();
if(state.token)connect();
