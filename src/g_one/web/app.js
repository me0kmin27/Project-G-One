const $=(selector,root=document)=>root.querySelector(selector);
const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];
const state={token:sessionStorage.getItem('g-one-token')||'',me:null,devices:[],support:[],audit:[]};
const labels={overview:'개요',devices:'장치',support:'원격 지원',audit:'감사 로그'};

async function api(path,options={}){
  const headers={'Content-Type':'application/json',...(options.headers||{})};
  if(state.token) headers.Authorization=`Bearer ${state.token}`;
  const response=await fetch(path,{...options,headers});
  if(response.status===204)return null;
  const data=await response.json().catch(()=>({detail:'서버 응답을 읽을 수 없습니다.'}));
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'요청을 처리하지 못했습니다.');
  return data;
}
function escapeHtml(value){return String(value).replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));}
function date(value){return new Intl.DateTimeFormat('ko-KR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value));}
function statusLabel(value){return {registered:'등록됨',revoked:'회수됨',pending:'대기 중',accepted:'진행 중',denied:'거절됨',ended:'종료됨',expired:'만료됨'}[value]||value;}
function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2800);}
function showError(error){const el=$('#globalError');el.textContent=error.message;el.classList.remove('hidden');}
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
  $('#recentDevices').innerHTML=deviceRows(state.devices.slice(0,4));$('#recentSupport').innerHTML=supportRows(state.support.slice(0,4));
  $('#supportDevice').innerHTML=active.map(d=>`<option value="${d.id}">${escapeHtml(d.name)} · ${escapeHtml(d.owner_id)}</option>`).join('');
  $('#devicesTable').innerHTML=state.devices.length?`<table class="data-table"><thead><tr><th>장치</th><th>소유자</th><th>플랫폼</th><th>상태</th><th>등록일</th><th></th></tr></thead><tbody>${state.devices.map(d=>`<tr><td><strong>${escapeHtml(d.name)}</strong></td><td>${escapeHtml(d.owner_id)}</td><td>${escapeHtml(d.platform)}</td><td><span class="status ${d.status}">${statusLabel(d.status)}</span></td><td>${date(d.created_at)}</td><td>${d.status==='registered'?`<button class="danger-btn" data-revoke="${d.id}">접근 회수</button>`:''}</td></tr>`).join('')}</tbody></table>`:empty('첫 장치를 등록해 보세요.');
  $('#supportTable').innerHTML=state.support.length?`<table class="data-table"><thead><tr><th>목적</th><th>장치</th><th>요청자</th><th>권한</th><th>상태</th><th>요청일</th></tr></thead><tbody>${state.support.map(r=>`<tr><td><strong>${escapeHtml(r.purpose)}</strong></td><td>${escapeHtml(deviceName(r.target_device_id))}</td><td>${escapeHtml(r.requester_id)}</td><td>${r.permissions.map(escapeHtml).join(', ')}</td><td><span class="status ${r.state}">${statusLabel(r.state)}</span></td><td>${date(r.created_at)}</td></tr>`).join('')}</tbody></table>`:empty('지원 요청이 없습니다.');
}
async function connect(){
  try{
    state.me=await api('/api/v1/me');sessionStorage.setItem('g-one-token',state.token);
    $('#workspaceName').textContent=state.me.tenant_id;$('#accountName').textContent=state.me.subject;$('#greetingName').textContent=state.me.subject;$('#avatar').textContent=state.me.subject[0].toUpperCase();$('#accountRole').textContent=state.me.roles.join(' · ');
    $('#loginView').classList.add('hidden');$('#appView').classList.remove('hidden');await loadData();
  }catch(error){state.token='';sessionStorage.removeItem('g-one-token');$('#loginError').textContent=`연결 실패: ${error.message}`;$('#loginView').classList.remove('hidden');$('#appView').classList.add('hidden');}
}
function go(page){$$('.page').forEach(el=>el.classList.toggle('hidden',el.dataset.view!==page));$$('.nav').forEach(el=>el.classList.toggle('active',el.dataset.page===page));$('#pageTitle').textContent=labels[page];$('#sidebar').classList.remove('open');if(page==='audit')loadAudit();}
async function loadAudit(){try{state.audit=await api('/api/v1/audit-events');$('#auditTable').innerHTML=state.audit.length?`<table class="data-table"><thead><tr><th>작업</th><th>행위자</th><th>대상</th><th>결과</th><th>시각</th></tr></thead><tbody>${state.audit.map(e=>`<tr><td><strong>${escapeHtml(e.action)}</strong></td><td>${escapeHtml(e.actor_id)}</td><td>${escapeHtml(e.target_type)} · ${escapeHtml(e.target_id.slice(0,8))}</td><td>${escapeHtml(e.outcome)}</td><td>${date(e.occurred_at)}</td></tr>`).join('')}</tbody></table>`:empty('감사 이벤트가 없습니다.');}catch(error){$('#auditTable').innerHTML=empty(`조회할 수 없습니다: ${error.message}`);}}

$('#loginForm').addEventListener('submit',async e=>{e.preventDefault();$('#loginError').textContent='';try{const result=await api('/api/v1/session/console',{method:'POST',body:JSON.stringify({subject:$('#subject').value,tenant_id:$('#tenant').value,password:$('#consolePassword').value})});state.token=result.access_token;await connect();}catch(error){$('#loginError').textContent=`로그인 실패: ${error.message}`;}});
$('#tokenToggle').onclick=()=>$('#tokenForm').classList.toggle('hidden');$('#tokenForm').addEventListener('submit',async e=>{e.preventDefault();state.token=$('#accessToken').value.trim();await connect();});
$('#logout').onclick=()=>{sessionStorage.removeItem('g-one-token');location.reload();};$('#menuButton').onclick=()=>$('#sidebar').classList.toggle('open');$$('.nav').forEach(el=>el.onclick=()=>go(el.dataset.page));$$('[data-go]').forEach(el=>el.onclick=()=>go(el.dataset.go));
$('#addDevice').onclick=()=>$('#deviceDialog').showModal();$$('[data-action="open-support"]').forEach(el=>el.onclick=()=>{if(!state.devices.some(d=>d.status==='registered'))return toast('먼저 활성 장치를 등록하세요.');$('#supportDialog').showModal();});$$('[data-close]').forEach(el=>el.onclick=()=>el.closest('dialog').close());
$('#deviceForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/v1/devices',{method:'POST',body:JSON.stringify({name:$('#deviceName').value})});e.target.reset();$('#deviceDialog').close();toast('장치를 등록했습니다.');await loadData();}catch(error){showError(error);}});
$('#supportForm').addEventListener('submit',async e=>{e.preventDefault();const permissions=$$('input[name="permission"]:checked').map(el=>el.value);if(!permissions.length)return toast('권한을 하나 이상 선택하세요.');try{await api('/api/v1/support-requests',{method:'POST',body:JSON.stringify({target_device_id:$('#supportDevice').value,purpose:$('#supportPurpose').value,permissions})});e.target.reset();$('#supportDialog').close();toast('지원 요청을 보냈습니다.');await loadData();}catch(error){showError(error);}});
$('#devicesTable').addEventListener('click',async e=>{const id=e.target.dataset.revoke;if(!id||!confirm('이 장치의 접근을 회수할까요?'))return;try{await api(`/api/v1/devices/${id}`,{method:'DELETE'});toast('장치 접근을 회수했습니다.');await loadData();}catch(error){showError(error);}});$('#refreshAudit').onclick=loadAudit;
if(state.token)connect();
