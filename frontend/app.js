
(() => {
  'use strict';
  if(location.protocol==='file:'){location.replace('http://127.0.0.1:8000/'+location.hash);return;}

  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
  const paths = {"logo": "<path d=\"M4 5h5v14H4zM10 10h5v9h-5zM16 3h5v16h-5z\" fill=\"currentColor\" stroke=\"none\"/>", "daily": "<path d=\"M14 3H5v18h14V8z\"/><path d=\"M14 3v5h5M8 12h8M8 16h6\"/>", "week": "<rect x=\"3\" y=\"5\" width=\"18\" height=\"16\" rx=\"2\"/><path d=\"M7 3v4M17 3v4M3 10h18M7 14h3M14 14h3M7 17h3\"/>", "history": "<path d=\"M3 10a9 9 0 1 1 1 8M3 4v6h6\"/><path d=\"M12 7v6l4 2\"/>", "spark": "<path d=\"m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6zM20 2v4M18 4h4\"/>", "upload": "<path d=\"M12 16V3m-5 5 5-5 5 5M4 14v6h16v-6\"/>", "check": "<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"m8 12 3 3 5-6\"/>", "trash": "<path d=\"M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7\"/>", "download": "<path d=\"M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5\"/>", "copy": "<rect x=\"8\" y=\"8\" width=\"12\" height=\"13\" rx=\"2\"/><path d=\"M16 8V3H3v13h5\"/>", "edit": "<path d=\"m15 4 5 5M4 20l5-1L21 7l-4-4L5 15z\"/>", "info": "<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M12 11v6M12 7v1\"/>", "folder": "<path d=\"M3 6h7l2 3h9v12H3zM3 6V3h7l2 3h7v3\"/>", "lock": "<rect x=\"5\" y=\"10\" width=\"14\" height=\"11\" rx=\"2\"/><path d=\"M8 10V7a4 4 0 0 1 8 0v3M12 14v3\"/>", "arrow": "<path d=\"M5 12h14m-5-5 5 5-5 5\"/>", "left": "<path d=\"m15 5-7 7 7 7\"/>", "right": "<path d=\"m9 5 7 7-7 7\"/>", "close": "<path d=\"m6 6 12 12M6 18 18 6\"/>", "save": "<path d=\"M4 3h13l3 3v15H4zM8 3v6h8V3M8 21v-8h8v8\"/>"};
  const ic = n => '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[n]+'</svg>';
  const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pad = n => String(n).padStart(2,'0');
  const dateKey = d => d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  const fromKey = s => new Date(s+'T12:00:00');
  const compact = s => s.replace(/-/g,'');
  const addDays = (s, n) => {const d=fromKey(s);d.setDate(d.getDate()+n);return dateKey(d);};
  const weekStart = s => {const d=fromKey(s);return addDays(s,-((d.getDay()+6)%7));};
  const weekAnchor = s => {const start=weekStart(s),end=fromKey(addDays(start,6)),first=dateKey(new Date(end.getFullYear(),end.getMonth(),1));return start<first?first:start;};
  const dateText = s => {const d=fromKey(s);return d.getFullYear()+'年'+(d.getMonth()+1)+'月'+d.getDate()+'日';};
  const shortDate = s => s.slice(5).replace('-','.');
  const today = dateKey(new Date());
  let active='daily', selectedDate=today, selectedWeekDate=weekAnchor(today), calendarMode='daily', calendarMonth=fromKey(today);
  let dailyFiles=[], records=[], weekRecords=[], messageTimer, loading={daily:false,weekly:false};
  const pending={daily:true,weekly:false},saving={daily:false,weekly:false};
  let generated={daily:false,weekly:false}, saved={daily:false,weekly:false}, demo={daily:false,weekly:false};
  let zipBusy=false;
  const previewStatus={daily:'待生成',weekly:'待生成'};
  let userProfile={name:'',role:'',dept:''},modelConfig={name:'',baseUrl:'',hasApiKey:false,configured:false},authorSnapshots={daily:null,weekly:null};
  const generationInfo={daily:{status:'ok',warnings:[]},weekly:{status:'ok',warnings:[]}};
  let historyItems=null,historyTotal=0,historyEpoch=0,dayEpoch=0,weekEpoch=0,uploadBusy=false,historyBusy=false;
  const size = n => n >= 1048576 ? (n/1048576).toFixed(1)+' MB' : n >= 1024 ? (n/1024).toFixed(1)+' KB' : n+' B';
  const safeName = s => s.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').replace(/[. ]+$/g,'').trim();
  const fileButton = (label, attrs, icon) => '<button class="icon-button" data-ant-component="Button" type="button" aria-label="'+escape(label)+'" '+attrs+'>'+ic(icon)+'</button>';
  function message(text, error=false) {
    clearTimeout(messageTimer);$('#message-content').textContent=text;$('#message-box').classList.toggle('error',error);$('#message-layer').hidden=false;
    messageTimer=setTimeout(()=>{$('#message-layer').hidden=true;},3000);
  }

  async function request(path,options={}) {
    const headers={'X-Work-Report':'1',...(options.headers||{})};
    const config={...options,headers};
    delete config.optional404;
    if(options.body!==undefined && !(options.body instanceof Blob)){headers['Content-Type']='application/json';config.body=JSON.stringify(options.body);}
    let response;
    try{response=await fetch('/api'+path,config);}catch{throw Object.assign(new Error('无法连接后端服务，请确认服务已启动。'),{code:'network_error'});}
    if(!response.ok){
      if(response.status===404&&options.optional404)return null;
      const data=await response.json().catch(()=>({})),error=data.error||{};
      throw Object.assign(new Error(error.message||'请求失败，请重试。'),{code:error.code,status:response.status});
    }
    return response;
  }
  async function api(path,options={}){const response=await request(path,options);return response?response.json():null;}
  const adaptFile=f=>({...f,blob:{size:f.size},demo:false});
  const adaptReport=r=>({...r,...r.profile,files:r.files.map(adaptFile),demo:false});
  const adaptModel=m=>({name:m.name,baseUrl:m.base_url,hasApiKey:m.has_api_key,configured:m.configured,keyPersisted:Boolean(m.key_persisted),credentialError:Boolean(m.credential_error)});
  function mergeRecords(items){for(const item of items){const record=adaptReport(item),at=records.findIndex(r=>r.id===record.id);if(at<0)records.push(record);else records[at]=record;}}
  function showWarnings(k,warnings){
    const el=$('#'+k+'-warnings');el.hidden=!warnings.length;
    el.innerHTML=warnings.length?'<strong>需要核对的信息</strong><ul>'+warnings.map(w=>'<li>'+escape(w)+'</li>').join('')+'</ul>':'';
  }
  function saveMode(k,isReport){
    const b=$('[data-save-draft="'+k+'"]');
    if(isReport){b.dataset.saveReport=k;b.innerHTML=ic('save')+'保存'+(k==='daily'?'日报':'周报');}
    else{delete b.dataset.saveReport;b.innerHTML=ic('save')+'保存草稿';}
  }
  function operationBusy(){return uploadBusy||Object.values(loading).some(Boolean)||Object.values(saving).some(Boolean);}
  function syncActions(){
    for(const k of ['daily','weekly']){
      const busy=pending[k]||loading[k]||saving[k]||(k==='daily'&&uploadBusy);
      $('#'+k+'-generate').disabled=busy||(k==='weekly'&&!weekRecords.length);
      $('[data-save-draft="'+k+'"]').disabled=busy;
      $('#'+k+'-notes').readOnly=busy;
      $('#'+k+'-report').contentEditable=String(!busy);
      $('#'+k+'-copy').disabled=busy||!generated[k];$('#'+k+'-edit').disabled=busy||!generated[k];
      $('#'+k+'-download').disabled=busy||zipBusy||!fileEntries(k).length;
      if(k==='daily'){$('#upload-drop').disabled=busy;$$('[data-remove]').forEach(b=>b.disabled=busy);}
    }
    const sourceHint=$('#weekly-source-hint');
    if(sourceHint)sourceHint.hidden=pending.weekly||weekRecords.length>0;
  }
  function canSwitchPeriod(){
    if(!operationBusy())return true;
    message('正在处理汇报，请完成后再切换日期或记录。');return false;
  }
  async function saveDraft(k){
    if(saving[k]||loading[k]||pending[k])return;
    const day=k==='daily'?selectedDate:selectedWeekDate;
    saving[k]=true;syncActions();
    try{await api('/drafts/'+k+'/'+day,{method:'PUT',body:{report_date:day,notes:$('#'+k+'-notes').value,file_ids:k==='daily'?dailyFiles.map(f=>f.id):[],points:generated[k]?readPoints(k):[],warnings:generationInfo[k].warnings,generation_status:generationInfo[k].status==='partial'?'partial':'ok',source_revisions:generationInfo[k].sourceRevisions||null}});}
    finally{saving[k]=false;syncActions();}
  }
  async function loadDay(day){
    const epoch=++dayEpoch;
    pending.daily=true;syncActions();
    try{
      const [raw,draft,files]=await Promise.all([api('/reports?kind=daily&start='+day+'&end='+day+'&limit=1').then(r=>r.items[0]||null),api('/drafts/daily/'+day),api('/files?report_date='+day)]);
      if(epoch!==dayEpoch||selectedDate!==day)return;
      authorSnapshots.daily=null;$('#daily-notes').value='';emptyPreview('daily');showWarnings('daily',[]);
      if(raw){mergeRecords([raw]);const r=adaptReport(raw);dailyFiles=r.files;authorSnapshots.daily=r.profile;$('#daily-notes').value=r.notes;setPoints('daily',r.points);generationInfo.daily={status:r.generation_status,warnings:r.warnings};showWarnings('daily',r.warnings);saved.daily=true;previewStatus.daily='已保存';saveMode('daily',true);}
      else dailyFiles=files.items.map(adaptFile);
      if(draft.draft){const d=draft.draft;dailyFiles=d.file_ids.map(id=>files.items.find(f=>f.id===id)).filter(Boolean).map(adaptFile);$('#daily-notes').value=d.notes;authorSnapshots.daily=null;if(d.points.length){setPoints('daily',d.points);generationInfo.daily={status:d.generation_status||'ok',warnings:d.warnings||[]};showWarnings('daily',generationInfo.daily.warnings);}else emptyPreview('daily');previewStatus.daily='草稿已恢复';saved.daily=false;}
      $('#daily-count').textContent=$('#daily-notes').value.length+' / 2000';renderFiles();updateDates();
    }catch(e){if(epoch===dayEpoch)message(e.message,true);}
    finally{if(epoch===dayEpoch){pending.daily=false;syncActions();}}
  }
  async function loadWeek(restore=!generated.weekly){
    const anchor=selectedWeekDate,epoch=++weekEpoch;
    pending.weekly=true;syncActions();
    try{
      const source=await api('/weeks/'+anchor+'/sources');if(epoch!==weekEpoch||anchor!==selectedWeekDate)return;mergeRecords(source.daily_reports);renderSources();
      if(restore){
        const [found,draft]=await Promise.all([api('/reports?kind=weekly&start='+source.period_start+'&end='+source.period_start+'&limit=1'),api('/drafts/weekly/'+anchor)]);
        if(epoch!==weekEpoch||anchor!==selectedWeekDate)return;
        const report=found.items[0];
        if(report){mergeRecords([report]);authorSnapshots.weekly=report.profile;$('#weekly-notes').value=report.notes;setPoints('weekly',report.points);generationInfo.weekly={status:report.generation_status,warnings:report.warnings,sourceRevisions:report.source_revisions};showWarnings('weekly',report.warnings);previewStatus.weekly='已保存';saved.weekly=true;}
        if(draft.draft){const d=draft.draft;$('#weekly-notes').value=d.notes;if(d.points.length){setPoints('weekly',d.points);generationInfo.weekly={status:d.generation_status||'ok',warnings:d.warnings||[],sourceRevisions:d.source_revisions};showWarnings('weekly',generationInfo.weekly.warnings);}else emptyPreview('weekly');previewStatus.weekly='草稿已恢复';saved.weekly=false;}
        $('#weekly-count').textContent=$('#weekly-notes').value.length+' / 2000';updatePaperMeta('weekly');
      }
      const revisions=Object.fromEntries(source.daily_reports.map(r=>[r.id,r.revision])),known=generationInfo.weekly.sourceRevisions;
      if(generated.weekly&&known&&JSON.stringify(Object.entries(known).sort())!==JSON.stringify(Object.entries(revisions).sort())){showWarnings('weekly',[...generationInfo.weekly.warnings,'日报来源已更新，请重新生成周报后保存。']);previewStatus.weekly='来源已更新 · 请重新生成';}
    }
    catch(e){if(epoch===weekEpoch)message(e.message,true);}
    finally{if(epoch===weekEpoch){pending.weekly=false;syncActions();}}
  }
  async function loadHistory(reset=true){
    if(!reset&&historyBusy)return;
    const epoch=++historyEpoch,day=$('#history-date').value,offset=reset?0:(historyItems||[]).length;
    historyBusy=true;$('#history-more').disabled=true;
    $('#history-date').classList.toggle('has-date',Boolean(day));
    try{const result=await api('/reports?limit=50&offset='+offset+(day?'&on_date='+day:''));if(epoch!==historyEpoch)return;mergeRecords(result.items);historyItems=(reset?[]:(historyItems||[])).concat(result.items.map(adaptReport));historyTotal=result.total;renderHistory();}
    catch(e){if(epoch===historyEpoch)message(e.message,true);}
    finally{if(epoch===historyEpoch){historyBusy=false;$('#history-more').disabled=false;}}
  }
  function profile(k) {return authorSnapshots[k]||userProfile;}
  function weekLabel() {
    const d=fromKey(weekAnchor(selectedWeekDate)),first=new Date(d.getFullYear(),d.getMonth(),1),offset=(first.getDay()+6)%7;
    return (d.getMonth()+1)+'月第'+(Math.floor((d.getDate()-1+offset)/7)+1)+'周';
  }
  function archiveName(k) {
    const p=userProfile;return (k==='daily'?compact(selectedDate):weekLabel())+'_'+safeName(p.role||'岗位')+'_'+safeName(p.name||'姓名')+'_工作汇报.zip';
  }
  function fileEntries(k) {
    return k==='daily'?dailyFiles.map(f=>({...f,date:selectedDate})):weekRecords.flatMap(r=>r.files.map(f=>({...f,date:r.date})));
  }
  function renamed(f,i) {
    const dot=f.name.lastIndexOf('.'),base=dot>0?f.name.slice(0,dot):f.name,ext=dot>0?f.name.slice(dot):'';
    return pad(i+1)+'_'+safeName(base)+'_'+compact(f.date)+safeName(ext);
  }
  function updatePackage(k) {
    const files=fileEntries(k);
    $('#'+k+'-archive-name').textContent=archiveName(k);
    $('#'+k+'-archive-files').innerHTML=files.slice(0,k==='weekly'?5:4).map((f,i)=>'<li title="'+escape(renamed(f,i))+'"><span class="tree-stem">'+(i===files.length-1?'└':'├')+'</span>'+ic('daily')+'<span class="file-label">'+escape(renamed(f,i))+'</span></li>').join('')+(files.length>(k==='weekly'?5:4)?'<li class="muted">另有 '+(files.length-(k==='weekly'?5:4))+' 个文件，将全部打包</li>':'');
    syncActions();
  }
  function updatePaperMeta(k) {
    const p=profile(k),range=weekStart(selectedWeekDate);
    $('#'+k+'-paper-title').textContent=k==='daily'?'本日工作汇报':'本周工作汇报';
    $('#'+k+'-paper-meta').textContent=(k==='daily'?dateText(selectedDate):weekLabel()+' · '+shortDate(range)+'—'+shortDate(addDays(range,6)))+' / '+(p.name||'姓名')+' / '+(p.role||'岗位')+(p.dept?' / '+p.dept:'');
    $('#'+k+'-archive-name').textContent=archiveName(k);
    updateWords(k);
  }
  function updateWords(k) {$('#'+k+'-word-count').textContent=$('#'+k+'-report').textContent.replace(/\s/g,'').length+' 字';}
  function setPoints(k,points) {
    saveMode(k,true);
    $('#'+k+'-report').innerHTML='<ol>'+points.map(p=>'<li data-source-refs="'+escape(JSON.stringify(p.source_refs||[]))+'"><strong>'+escape(p.title)+'</strong><p>'+escape(p.text)+'</p></li>').join('')+'</ol>';
    generated[k]=true;$('#'+k+'-paper-content').hidden=false;$('#'+k+'-empty').hidden=true;$('#'+k+'-copy').disabled=false;$('#'+k+'-edit').disabled=false;updateWords(k);
  }
  function emptyPreview(k) {
    saveMode(k,false);showWarnings(k,[]);
    generated[k]=false;$('#'+k+'-paper-content').hidden=true;$('#'+k+'-empty').hidden=false;previewStatus[k]='待生成';$('#'+k+'-copy').disabled=true;$('#'+k+'-edit').disabled=true;
    generationInfo[k]={status:'ok',warnings:[]};saved[k]=false;
  }
  function renderFiles() {
    $('#file-total').textContent='已添加 '+dailyFiles.length+' 个文件';
    $('#upload-list').innerHTML=dailyFiles.map((f,i)=>{
      const ext=f.name.split('.').pop().toLowerCase(),type=ext.slice(0,4).toUpperCase();
      return '<div class="file-row" role="listitem"><span class="file-type '+(ext==='csv'?'csv':ext==='svg'?'svg':'')+'">'+escape(type)+'</span><div class="grow"><div class="file-name" title="'+escape(f.name)+'">'+escape(f.name)+'</div><div class="file-meta">'+ic('check')+'<span>'+size(f.blob.size)+' · '+(f.demo?'示例成果':'已就绪')+'</span></div></div><div class="file-actions">'+fileButton('下载原文件 '+f.name,'data-original="'+i+'"','download')+fileButton('移除 '+f.name,'data-remove="'+i+'"','trash')+'</div></div>';
    }).join('');
    $$('.file-meta .icon').forEach(x=>x.classList.add('tiny-check'));updatePackage('daily');
  }
  function renderSources() {
    const start=weekStart(selectedWeekDate),end=addDays(start,6);
    weekRecords=records.filter(r=>r.kind==='daily'&&r.date>=start&&r.date<=end).sort((a,b)=>a.date.localeCompare(b.date));
    const files=weekRecords.reduce((s,r)=>s+r.files.length,0),points=weekRecords.reduce((s,r)=>s+r.points.length,0);
    $('#source-days').innerHTML=weekRecords.length+'<em>天</em>';$('#source-files').innerHTML=files+'<em>份</em>';$('#source-points').innerHTML=points+'<em>项</em>';
    $('#week-days').innerHTML=Array.from({length:7},(_,i)=>{
      const day=addDays(start,i),has=weekRecords.some(r=>r.date===day);
      return '<div class="day-cell'+(has?' has-report':'')+'"><span>周'+['一','二','三','四','五','六','日'][i]+'</span><strong>'+fromKey(day).getDate()+'</strong><div class="day-dot"></div><span>'+(has?'已关联':day>today?'待开始':i>4?'休息日':'无日报')+'</span></div>';
    }).join('');
    $('#source-list').innerHTML=weekRecords.map(r=>'<div class="source-item"><div class="row"><span class="source-icon">'+ic('daily')+'</span><div class="grow"><strong>'+shortDate(r.date)+' · '+escape(r.points[0]?.title||'工作日报')+'</strong><div class="small muted">'+r.points.length+' 项工作 · '+r.files.length+' 份成果'+(r.demo?' · 示例记录':'')+'</div></div><span class="source-status">'+ic('check')+'已关联</span>'+fileButton('查看 '+r.date+' 日报','data-open-record="'+escape(r.id)+'"','arrow')+'</div></div>').join('');
    updatePackage('weekly');updatePaperMeta('weekly');
  }
  function updateDates() {
    $('#daily-value').textContent=selectedDate.replace(/-/g,' / ');
    const start=weekStart(selectedWeekDate);$('#weekly-value').textContent=weekLabel()+' · '+shortDate(start)+' — '+shortDate(addDays(start,6));
    updatePaperMeta('daily');updatePaperMeta('weekly');updatePackage('daily');renderSources();
  }
  function route(k) {
    active=k;$$('[data-page-scope]').forEach(x=>x.hidden=x.dataset.pageScope!==k);
    $$('.menu-leaf[data-route]').forEach(x=>{if(x.dataset.route===k)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});
    $('#breadcrumb-current').textContent={daily:'日报工作台',weekly:'周报工作台',history:'历史汇报'}[k];
    if(k==='weekly'){renderSources();loadWeek();}if(k==='history'){renderHistory();loadHistory();}$('.workspace').scrollTop=0;
    history.replaceState(null,'','#'+k);
  }
  function readPoints(k) {
    const items=$$('li',$('#'+k+'-report'));return items.length?items.map(li=>({title:$('strong',li)?.textContent||li.textContent,text:$('p',li)?.textContent||'',source_refs:JSON.parse(li.dataset.sourceRefs||'[]')})):$('#'+k+'-report').innerText.split('\n').filter(Boolean).map(text=>({title:text,text:''}));
  }
  function validate(k) {
    const p=profile(k);
    if(!p.name||!p.role){openSettings('profile');message('请先完善姓名和岗位，再生成或下载汇报。',true);return false;}
    return true;
  }

  async function generate(k){
    if(operationBusy()||pending[k]||!validate(k))return;
    const notes=$('#'+k+'-notes').value.trim(),day=k==='daily'?selectedDate:selectedWeekDate;
    if(k==='daily'&&!dailyFiles.length&&!notes){$('#daily-error').textContent='请填写工作内容或上传至少一份成果文件。';$('#daily-error').hidden=false;$('#daily-notes').focus();return;}
    if(k==='weekly'&&!weekRecords.length){$('#weekly-error').textContent='本周还没有已保存的日报，请先保存日报。';$('#weekly-error').hidden=false;return;}
    if(!modelConfig.configured){openSettings('api');message('请先配置模型服务，保存后再生成汇报。',true);return;}
    const oldStatus=previewStatus[k];
    $('#'+k+'-error').hidden=true;loading[k]=true;$('#'+k+'-generate').disabled=true;$('#'+k+'-generate').setAttribute('aria-busy','true');$('#'+k+'-loading').hidden=false;$('#'+k+'-paper-content').hidden=true;$('#'+k+'-empty').hidden=true;previewStatus[k]='正在调用模型';updatePackage(k);
    try{
      const body=k==='daily'?{report_date:day,work_content:notes,file_ids:dailyFiles.map(f=>f.id),previous_report:generated[k]?readPoints(k):[]}:{anchor_date:day,requirements:notes,previous_report:generated[k]?readPoints(k):[]};
      const result=await api('/reports/'+k+'/generate',{method:'POST',body});
      generationInfo[k]={status:result.status,warnings:result.warnings,sourceRevisions:result.source_revisions};
      if(result.status==='insufficient_information'){emptyPreview(k);showWarnings(k,result.warnings);message('可用信息不足，请补充工作内容或可读取的成果文件。',true);return;}
      authorSnapshots[k]={...userProfile};setPoints(k,result.items);saved[k]=false;demo[k]=false;showWarnings(k,result.warnings);updatePaperMeta(k);
      previewStatus[k]='已生成 · 待保存';$('#'+k+'-kicker').textContent='AI 生成 · 请核对工作事实';
      $('#'+k+'-generate-label').textContent='重新生成'+(k==='daily'?'日报':'周报');
      message((k==='daily'?'日报':'周报')+'已生成，可编辑并保存。');
    }catch(e){
      $('#'+k+'-paper-content').hidden=!generated[k];$('#'+k+'-empty').hidden=generated[k];previewStatus[k]=oldStatus;
      if(e.code==='model_not_configured')openSettings('api');
      message(e.message,true);
    }finally{loading[k]=false;$('#'+k+'-loading').hidden=true;$('#'+k+'-generate').disabled=false;$('#'+k+'-generate').removeAttribute('aria-busy');updatePackage(k);if(k==='weekly')renderSources();}
  }
  async function saveReport(k){
    if(operationBusy()||pending[k]||!generated[k]||!validate(k))return;
    const day=k==='daily'?selectedDate:selectedWeekDate,start=k==='daily'?day:weekStart(day),current=records.find(r=>r.kind===k&&r.period_start===start);
    saving[k]=true;syncActions();
    try{
      const result=await api('/reports/'+k+'/'+day,{method:'PUT',body:{points:readPoints(k),notes:$('#'+k+'-notes').value,file_ids:k==='daily'?dailyFiles.map(f=>f.id):[],warnings:generationInfo[k].warnings,generation_status:generationInfo[k].status==='partial'?'partial':'ok',expected_revision:current?.revision||0,source_revisions:k==='weekly'?generationInfo[k].sourceRevisions||null:null}});
      mergeRecords([result]);authorSnapshots[k]=result.profile;saved[k]=true;previewStatus[k]='已保存';updatePaperMeta(k);renderSources();message((k==='daily'?'日报':'周报')+'已保存到后端'+(k==='daily'?'，可用于生成周报。':'。'));
    }catch(e){message(e.message,true);}finally{saving[k]=false;syncActions();}
  }
  function invalidate(k){if(generated[k]){previewStatus[k]='内容有变化 · 待重新生成';saved[k]=false;}}
  function loadRecord(id) {
    if(!canSwitchPeriod())return;
    const r=records.find(r=>r.id===id);if(!r)return;
    if(r.kind==='daily'){dayEpoch++;pending.daily=false;}else{weekEpoch++;pending.weekly=false;}
    const k=r.kind;authorSnapshots[k]={name:r.name,role:r.role,dept:r.dept||''};
    $('#'+k+'-notes').value=r.notes||'';$('#'+k+'-count').textContent=(r.notes||'').length+' / 2000';
    if(k==='daily'){selectedDate=r.date;dailyFiles=r.files.map(f=>({...f}));renderFiles();}else selectedWeekDate=weekAnchor(r.date);
    setPoints(k,r.points);generationInfo[k]={status:r.generation_status||'ok',warnings:r.warnings||[],sourceRevisions:r.source_revisions};showWarnings(k,r.warnings||[]);demo[k]=r.demo;saved[k]=!r.demo;previewStatus[k]=r.demo?'示例预览':'已保存';
    updateDates();route(k);
  }
  function renderHistory() {
    const day=$('#history-date').value;
    const rows=(historyItems||records).filter(r=>r.kind!=='draft'&&(!day||(r.period_start<=day&&r.period_end>=day))).sort((a,b)=>b.date.localeCompare(a.date));
    $('#history-count').textContent='共 '+(historyItems===null?rows.length:historyTotal)+' 份记录';$('#history-empty').hidden=rows.length>0;
    $('#history-empty .ant-empty-description strong').textContent=day?'该日期暂无汇报':'还没有保存的汇报';
    $('#history-clear-date').disabled=!day;
    $('#history-more').hidden=historyItems===null||historyItems.length>=historyTotal;
    $('#history-list').innerHTML=rows.map(r=>'<article class="history-card"><div class="row spread"><span class="history-label">'+(r.kind==='daily'?'日报':'周报')+'</span><span class="small muted">'+dateText(r.date)+(r.demo?' · 示例':' · 已保存')+'</span></div><h2>'+escape(r.name)+'的'+(r.kind==='daily'?'工作日报':'工作周报')+'</h2><p>'+escape(r.points.map(p=>p.title).slice(0,2).join('；'))+'</p><div class="row spread"><span class="small muted">'+r.points.length+' 项工作 · '+r.files.length+' 份成果</span><button class="btn sm" data-ant-component="Button" type="button" data-open-record="'+escape(r.id)+'">查看汇报 '+ic('arrow')+'</button></div></article>').join('');
  }
  function triggerDownload(blob,name) {
    const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),2000);
  }

  async function downloadZip(k){
    if(zipBusy||pending[k]||loading[k]||saving[k]||!validate(k))return;
    zipBusy=true;const button=$('#'+k+'-download');button.disabled=true;button.innerHTML=ic('download')+'正在打包…';
    try{
      const response=await request('/archives',{method:'POST',body:{kind:k,report_date:k==='daily'?selectedDate:selectedWeekDate,file_ids:k==='daily'?dailyFiles.map(f=>f.id):[]}});
      const disposition=response.headers.get('Content-Disposition')||'',match=disposition.match(/filename\*=UTF-8''([^;]+)/i);
      triggerDownload(await response.blob(),match?decodeURIComponent(match[1]):archiveName(k));message('成果压缩包已下载。');
    }catch(e){message(e.message,true);}finally{zipBusy=false;button.innerHTML=ic('download')+'下载成果压缩包';updatePackage(k);}
  }
  function closeCalendar(focus=false){$('#calendar-popup').hidden=true;$$('[data-date-trigger]').forEach(b=>b.setAttribute('aria-expanded','false'));if(focus)$('#'+calendarMode+'-trigger').focus();}
  function positionCalendar(){
    const p=$('#calendar-popup');if(p.hidden)return;const r=$('#'+calendarMode+'-trigger').getBoundingClientRect();
    p.style.left=Math.min(Math.max(8,r.left),innerWidth-p.offsetWidth-8)+'px';p.style.top=(r.bottom+8+p.offsetHeight>innerHeight?Math.max(8,r.top-p.offsetHeight-8):r.bottom+8)+'px';
  }
  function renderCalendar(){
    const year=calendarMonth.getFullYear(),month=calendarMonth.getMonth(),first=dateKey(new Date(year,month,1)),start=weekStart(first),value=calendarMode==='daily'?selectedDate:selectedWeekDate;
    const weekly=calendarMode==='weekly',popup=$('#calendar-popup');
    popup.classList.toggle('is-week-picker',weekly);popup.setAttribute('aria-label',weekly?'选择汇报周':'选择汇报日期');
    $('.calendar-weekdays').hidden=weekly;$('#calendar-days').hidden=weekly;$('#calendar-weeks').hidden=!weekly;
    $('#calendar-title').textContent=year+'年 '+(month+1)+'月';$('#calendar-today').textContent=weekly?'本周':'回到今天';
    if(weekly){
      $('#calendar-days').innerHTML='';
      const nextFirst=dateKey(new Date(year,month+1,1)),count=Math.round((fromKey(weekStart(nextFirst))-fromKey(start))/604800000);
      $('#calendar-weeks').innerHTML=Array.from({length:count},(_,i)=>{
        const begin=addDays(start,i*7),end=addDays(begin,6),anchor=begin<first?first:begin;
        const selected=weekStart(value)===begin&&fromKey(value).getMonth()===month&&fromKey(value).getFullYear()===year;
        const crossYear=fromKey(begin).getFullYear()!==year||fromKey(end).getFullYear()!==year;
        const range=crossYear?begin.replace(/-/g,'.')+' — '+end.replace(/-/g,'.'):shortDate(begin)+' — '+shortDate(end);
        return '<button type="button" class="week-option" role="option" data-week-anchor="'+anchor+'" aria-selected="'+selected+'" tabindex="'+(selected?0:-1)+'" aria-label="'+year+'年'+(month+1)+'月第'+(i+1)+'周，'+range+'"><span><strong>第'+(i+1)+'周</strong><small>'+range+'</small></span>'+(selected?ic('check'):'')+'</button>';
      }).join('');
      if(!$('#calendar-weeks [aria-selected="true"]'))$('#calendar-weeks .week-option').tabIndex=0;
    }else{
      $('#calendar-weeks').innerHTML='';
      $('#calendar-days').innerHTML=Array.from({length:42},(_,i)=>{
        const day=addDays(start,i),d=fromKey(day),selected=day===value;
        return '<button type="button" role="gridcell" data-day="'+day+'" aria-label="'+dateText(day)+'" aria-selected="'+selected+'" tabindex="'+(selected?0:-1)+'" class="'+(d.getMonth()!==month?'other ':'')+(selected?'selected ':'')+(day===today?'today':'')+'">'+d.getDate()+'</button>';
      }).join('');
    }
    positionCalendar();
  }
  function focusCalendarChoice(){
    const target=calendarMode==='weekly'?$('#calendar-weeks [aria-selected="true"]')||$('#calendar-weeks .week-option'):$('#calendar-days .selected')||$('#calendar-days [data-day]');
    target?.focus();
  }
  async function selectWeek(anchor){
    if(!canSwitchPeriod())return;
    anchor=weekAnchor(anchor);
    const changed=weekStart(anchor)!==weekStart(selectedWeekDate);
    selectedWeekDate=anchor;
    if(changed){authorSnapshots.weekly=null;$('#weekly-notes').value='';$('#weekly-count').textContent='0 / 2000';generationInfo.weekly={status:'ok',warnings:[]};emptyPreview('weekly');}
    updateDates();
    if(changed)await loadWeek();
  }

  async function chooseDate(day){
    if(!canSwitchPeriod())return;
    closeCalendar(true);
    if(calendarMode==='daily'){selectedDate=day;authorSnapshots.daily=null;dailyFiles=[];$('#daily-notes').value='';$('#daily-count').textContent='0 / 2000';emptyPreview('daily');updateDates();await loadDay(day);}
    else await selectWeek(day);
  }
  async function addFiles(list){
    if(operationBusy()||pending.daily){message('请等待当前操作完成后再上传。');return;}
    const day=selectedDate;uploadBusy=true;syncActions();let count=0;
    try{
      for(const file of list){
        if(dailyFiles.length>=30){message('每天最多选择 30 个成果文件，剩余文件未上传。',true);break;}
        if(file.size>50*1024*1024||!file.size){message('已跳过空文件或超过 50 MB 的文件：'+file.name,true);continue;}
        const item=await api('/files?report_date='+day+'&filename='+encodeURIComponent(file.name),{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}});
        if(day===selectedDate){dailyFiles.push(adaptFile(item));renderFiles();invalidate('daily');}count++;
      }
      if(day===selectedDate&&count){await saveDraft('daily');$('#daily-error').hidden=true;}
      if(count)message('已上传 '+count+' 个成果文件至 '+day+'。');
    }catch(e){message(e.message,true);}finally{uploadBusy=false;syncActions();}
  }
  $('#upload-drop').addEventListener('click',()=>$('#file-input').click());
  $('#file-input').addEventListener('change',e=>{addFiles(Array.from(e.target.files));e.target.value='';});
  ['dragenter','dragover'].forEach(n=>$('#upload-drop').addEventListener(n,e=>{e.preventDefault();$('#upload-drop').classList.add('drag-over');}));
  ['dragleave','drop'].forEach(n=>$('#upload-drop').addEventListener(n,e=>{e.preventDefault();$('#upload-drop').classList.remove('drag-over');}));
  $('#upload-drop').addEventListener('drop',e=>addFiles(Array.from(e.dataTransfer.files)));
  for(const k of ['daily','weekly']){
    $('#'+k+'-form').addEventListener('submit',e=>{e.preventDefault();generate(k);});
    $('#'+k+'-generate').addEventListener('click',()=>generate(k));
    $('#'+k+'-notes').addEventListener('input',e=>{$('#'+k+'-count').textContent=e.target.value.length+' / 2000';$('#'+k+'-error').hidden=true;invalidate(k);});
    $('#'+k+'-report').addEventListener('input',()=>{updateWords(k);saved[k]=false;previewStatus[k]='已编辑 · 待保存';});
  }
  document.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.route)route(b.dataset.route);
    else if(b.hasAttribute('data-collapse')){const app=$('[data-web-app]');app.classList.toggle('is-collapsed');$('.collapse-label').textContent=app.classList.contains('is-collapsed')?'展开导航':'收起导航';}
    else if(b.dataset.download)downloadZip(b.dataset.download);
    else if(b.dataset.copy){
      const k=b.dataset.copy,text=$('#'+k+'-paper-title').textContent+'\n'+$('#'+k+'-paper-meta').textContent+'\n\n'+readPoints(k).map((p,i)=>(i+1)+'. '+p.title+(p.text?'\n'+p.text:'')).join('\n\n');
      try{await navigator.clipboard.writeText(text);message('汇报正文已复制。');}catch{const t=document.createElement('textarea');t.value=text;document.body.append(t);t.select();document.execCommand('copy');t.remove();message('汇报正文已复制。');}
    }
    else if(b.dataset.edit){$('#'+b.dataset.edit+'-report').focus();message('可以直接修改正文，编辑后记得保存。');}
    else if(b.dataset.saveReport)await saveReport(b.dataset.saveReport);
    else if(b.dataset.saveDraft){try{await saveDraft(b.dataset.saveDraft);message('草稿已保存到后端。');}catch(e){message(e.message,true);}}
    else if(b.hasAttribute('data-remove')){if(operationBusy()||pending.daily)return;dailyFiles.splice(Number(b.dataset.remove),1);renderFiles();invalidate('daily');try{await saveDraft('daily');}catch(e){message(e.message,true);}}
    else if(b.hasAttribute('data-original')){const f=dailyFiles[Number(b.dataset.original)];try{const response=await request('/files/'+f.id+'/download');triggerDownload(await response.blob(),f.name);}catch(e){message(e.message,true);}}
    else if(b.dataset.openRecord)loadRecord(b.dataset.openRecord);
    else if(b.dataset.dateTrigger){calendarMode=b.dataset.dateTrigger;calendarMonth=fromKey(calendarMode==='daily'?selectedDate:selectedWeekDate);const opening=$('#calendar-popup').hidden;closeCalendar();if(opening){$('#calendar-popup').hidden=false;b.setAttribute('aria-expanded','true');renderCalendar();focusCalendarChoice();}}
    else if(b.dataset.weekAnchor)await chooseDate(b.dataset.weekAnchor);
    else if(b.dataset.day)chooseDate(b.dataset.day);
    else if(b.hasAttribute('data-week-shift'))await selectWeek(addDays(selectedWeekDate,Number(b.dataset.weekShift)*7));
  });
  $('#calendar-prev').onclick=()=>{calendarMonth=new Date(calendarMonth.getFullYear(),calendarMonth.getMonth()-1,1);renderCalendar();};
  $('#calendar-next').onclick=()=>{calendarMonth=new Date(calendarMonth.getFullYear(),calendarMonth.getMonth()+1,1);renderCalendar();};
  $('#calendar-today').onclick=()=>chooseDate(today);
  document.addEventListener('pointerdown',e=>{if(!$('#calendar-popup').hidden&&!$('#calendar-popup').contains(e.target)&&!e.target.closest('[data-date-trigger]'))closeCalendar();});
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&$('#settings-modal').hidden&&$('#account-dropdown').hidden){closeCalendar(true);}
    if(e.target.matches('[data-day]')){
      const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7}[e.key];
      if(delta){e.preventDefault();const next=addDays(e.target.dataset.day,delta),el=$('[data-day="'+next+'"]');if(el)el.focus();else{calendarMonth=fromKey(next);renderCalendar();$('[data-day="'+next+'"]')?.focus();}}
    }
    if(e.target.matches('[data-week-anchor]')){
      const options=$$('[data-week-anchor]'),index=options.indexOf(e.target);let next;
      if(e.key==='ArrowDown')next=(index+1)%options.length;
      if(e.key==='ArrowUp')next=(index+options.length-1)%options.length;
      if(e.key==='Home')next=0;
      if(e.key==='End')next=options.length-1;
      if(next!==undefined){e.preventDefault();options.forEach((option,i)=>option.tabIndex=i===next?0:-1);options[next].focus();}
    }
  });
  addEventListener('resize',positionCalendar);$('.workspace').addEventListener('scroll',()=>closeCalendar(),{passive:true});
  $('#history-date').addEventListener('input',()=>{$('#history-date').classList.toggle('has-date',Boolean($('#history-date').value));});
  $('#history-date').addEventListener('change',()=>{if($('#history-date').validity.valid&&active==='history')loadHistory();});
  $('#history-clear-date').addEventListener('click',()=>{$('#history-date').value='';loadHistory();});
  let settingsMode='profile',settingsReturn=null,workspaceOverflow='',settingsBusy=false;
  const accountTrigger=$('#account-trigger'),accountDropdown=$('#account-dropdown'),settingsModal=$('#settings-modal');
  function syncAccount(){
    const initial=Array.from(userProfile.name)[0]||'我';
    for(const id of ['top-avatar','menu-avatar','profile-avatar'])$('#'+id).textContent=initial;
    $('.side-user .avatar').textContent=initial;
    const side=$('.side-user>span');side.replaceChildren(document.createTextNode(userProfile.name||'未填写姓名'));const small=document.createElement('small');small.textContent=[userProfile.role,userProfile.dept].filter(Boolean).join(' · ')||'完善个人信息';side.append(small);
    $('#menu-name').textContent=userProfile.name||'未填写姓名';$('#menu-profile').textContent=[userProfile.role,userProfile.dept].filter(Boolean).join(' · ')||'完善个人信息';
    $('#api-menu-status').textContent=modelConfig.name&&modelConfig.baseUrl?(modelConfig.hasApiKey?'配置已保存':'待填写 Key'):'未配置';
    for(const k of ['daily','weekly']){
      const guidance=$('#'+k+'-setup-guidance');if(!guidance)continue;
      const needsProfile=!userProfile.name||!userProfile.role,needsModel=!modelConfig.configured;
      guidance.hidden=!needsProfile&&!needsModel;
      const label=$('.setup-guidance-label',guidance);label.textContent=needsProfile&&needsModel?'生成汇报前，请完善个人信息并配置模型服务。':needsProfile?'生成汇报前，请完善姓名和岗位。':'生成汇报前，请配置模型服务。';
      $('[data-setup-mode="profile"]',guidance).hidden=!needsProfile;
      $('[data-setup-mode="api"]',guidance).hidden=!needsModel;
    }
  }
  function positionAccount(){
    if(accountDropdown.hidden)return;
    const r=accountTrigger.getBoundingClientRect();accountDropdown.style.top=(r.bottom+8)+'px';accountDropdown.style.left=Math.max(8,Math.min(r.right-260,innerWidth-268))+'px';
  }
  function closeAccount(focus=false){accountDropdown.hidden=true;accountTrigger.setAttribute('aria-expanded','false');if(focus)accountTrigger.focus();}
  function showAccount(){closeCalendar();accountDropdown.hidden=false;accountTrigger.setAttribute('aria-expanded','true');syncAccount();positionAccount();$('[role="menuitem"]',accountDropdown).focus();}
  accountTrigger.addEventListener('click',()=>{if(accountDropdown.hidden)showAccount();else closeAccount(true);});
  accountTrigger.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();showAccount();}});
  accountDropdown.addEventListener('keydown',e=>{
    const items=$$('[role="menuitem"]',accountDropdown),index=items.indexOf(document.activeElement);let next;
    if(e.key==='ArrowDown')next=(index+1)%items.length;if(e.key==='ArrowUp')next=(index+items.length-1)%items.length;if(e.key==='Home')next=0;if(e.key==='End')next=items.length-1;
    if(next!==undefined){e.preventDefault();items[next].focus();}
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeAccount(true);}if(e.key==='Tab')closeAccount();
  });
  document.addEventListener('pointerdown',e=>{if(!accountDropdown.contains(e.target)&&!accountTrigger.contains(e.target))closeAccount();});
  addEventListener('resize',positionAccount);
  function setSettingError(id,text){
    const input=$('#'+id),err=$('#'+id+'-error');input.setAttribute('aria-invalid',String(Boolean(text)));err.textContent=text;err.hidden=!text;
  }
  function syncSettingsActions(){
    $('#save-settings').disabled=settingsBusy;
    $('#test-model').disabled=settingsBusy||!modelConfig.configured;
    $('#clear-model-key').disabled=settingsBusy||!(modelConfig.hasApiKey||modelConfig.credentialError);
  }
  function updateKeyHint(){
    $('#model-api-key').placeholder=modelConfig.hasApiKey?'已保存，留空则保留当前 Key':'请输入 API Key';
    $('#key-storage-note').textContent=modelConfig.credentialError?'已保存的 Key 无法读取或格式无效，请重新填写真实密钥并保存。':'API Key 会加密保存在本机，重启后自动读取。';
  }
  function openSettings(mode){
    settingsMode=mode;settingsReturn=document.activeElement.closest('#account-dropdown')?accountTrigger:document.activeElement;
    closeAccount();closeCalendar();
    $('#profile-settings').hidden=mode!=='profile';$('#api-settings').hidden=mode!=='api';
    $('#settings-title').textContent=mode==='profile'?'个人信息':'模型 API 设置';
    $('#settings-description').textContent=mode==='profile'?'统一用于日报、周报与成果压缩包署名':'配置实际用于生成汇报的模型服务';
    $('#save-settings').textContent=mode==='profile'?'保存个人信息':'保存模型配置';$('#test-model').hidden=mode!=='api';$('#test-model').disabled=!modelConfig.configured;
    $('#clear-model-key').hidden=mode!=='api';syncSettingsActions();
    for(const n of ['name','role','dept'])$('#profile-'+n).value=userProfile[n];
    $('#model-name').value=modelConfig.name;$('#model-base-url').value=modelConfig.baseUrl;$('#model-api-key').value='';updateKeyHint();
    $('#model-api-key').type='password';$('#toggle-api-key').setAttribute('aria-pressed','false');$('#toggle-api-key').setAttribute('aria-label','显示 API Key');
    for(const id of ['profile-name','profile-role','profile-dept','model-name','model-base-url','model-api-key'])setSettingError(id,'');
    settingsModal.hidden=false;$('[data-web-app]').inert=true;workspaceOverflow=$('.workspace').style.overflowY;$('.workspace').style.overflowY='hidden';
    $('#'+(mode==='profile'?'profile-name':'model-name')).focus();
  }
  function closeSettings(){
    settingsModal.hidden=true;$('[data-web-app]').inert=false;$('.workspace').style.overflowY=workspaceOverflow;
    $('#model-api-key').value='';$('#model-api-key').type='password';
    if(settingsReturn?.isConnected)settingsReturn.focus();else accountTrigger.focus();
  }

  async function saveSettings(){
    if(settingsBusy)return;
    if(operationBusy()){message('正在处理汇报，请完成后再修改设置。',true);return;}
    let first=null;const error=(id,text)=>{setSettingError(id,text);if(text&&!first)first=$('#'+id);};
    if(settingsMode==='profile'){
      const next={name:$('#profile-name').value.trim(),role:$('#profile-role').value.trim(),dept:$('#profile-dept').value.trim()};
      error('profile-name',next.name?'':'请填写姓名。');error('profile-role',next.role?'':'请填写岗位。');if(first){first.focus();return;}
      settingsBusy=true;syncSettingsActions();
      try{userProfile=await api('/profile',{method:'PUT',body:next});authorSnapshots={daily:null,weekly:null};syncAccount();for(const k of ['daily','weekly']){updatePaperMeta(k);updatePackage(k);}renderSources();closeSettings();message('个人信息已保存，日报与周报署名已同步。');}
      catch(e){message(e.message,true);}finally{settingsBusy=false;syncSettingsActions();}
    }else{
      const next={name:$('#model-name').value.trim(),base_url:$('#model-base-url').value.trim(),api_key:$('#model-api-key').value.trim()};
      error('model-name',next.name?'':'请输入模型名称。');let valid=false;try{const u=new URL(next.base_url);valid=['https:','http:'].includes(u.protocol)&&!u.username&&!u.password&&!u.search&&!u.hash;}catch{}
      error('model-base-url',valid?'':'请输入有效的 HTTP 或 HTTPS Base URL。');
      const invalidKey=next.api_key&&(!/^[\x21-\x7E]+$/.test(next.api_key)||/^\*+$/.test(next.api_key));
      error('model-api-key',invalidKey?'API Key 格式无效，请从模型服务商复制真实密钥，不要填写中文、空格或密码遮罩。':!next.api_key&&(!modelConfig.hasApiKey||next.base_url.replace(/\/$/,'')!==modelConfig.baseUrl)?'首次配置或修改地址后，请填写 API Key。':'');
      if(first){first.focus();return;}if(!next.api_key)delete next.api_key;
      settingsBusy=true;syncSettingsActions();
      try{modelConfig=adaptModel(await api('/model-settings',{method:'PUT',body:next}));syncAccount();closeSettings();message('模型配置已保存，现在可以生成汇报。');}
      catch(e){message(e.message,true);}finally{settingsBusy=false;syncSettingsActions();}
    }
  }
  document.addEventListener('click',e=>{const open=e.target.closest('[data-open-settings],[data-setup-mode]');if(open){openSettings(open.dataset.openSettings||open.dataset.setupMode);return;}if(e.target.closest('[data-close-settings]')||e.target.hasAttribute('data-settings-mask'))closeSettings();});
  $('#save-settings').addEventListener('click',saveSettings);
  for(const id of ['profile-settings','api-settings'])$('#'+id).addEventListener('submit',e=>{e.preventDefault();saveSettings();});
  for(const id of ['profile-name','profile-role','profile-dept','model-name','model-base-url','model-api-key'])$('#'+id).addEventListener('input',()=>setSettingError(id,''));
  $('#toggle-api-key').addEventListener('click',()=>{const input=$('#model-api-key'),show=input.type==='password';input.type=show?'text':'password';$('#toggle-api-key').setAttribute('aria-pressed',String(show));$('#toggle-api-key').setAttribute('aria-label',show?'隐藏 API Key':'显示 API Key');});
  settingsModal.addEventListener('keydown',e=>{
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeSettings();return;}
    if(e.key==='Tab'){
      const targets=$$('button,input,[tabindex="0"]',settingsModal).filter(x=>!x.disabled&&x.getClientRects().length),first=targets[0],last=targets.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
  });
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&!settingsModal.hidden){e.preventDefault();e.stopImmediatePropagation();closeSettings();}
  },true);


  async function init(){
    for(const k of ['daily','weekly'])emptyPreview(k);
    renderFiles();updateDates();
    try{
      const bootstrap=await api('/bootstrap');userProfile=bootstrap.profile;modelConfig=adaptModel(bootstrap.model);mergeRecords(bootstrap.reports);syncAccount();updateDates();await loadDay(today);
      route(['daily','weekly','history'].includes(location.hash.slice(1))?location.hash.slice(1):'daily');
    }catch(e){message(e.message,true);}
    $('#today-display').textContent=dateText(today)+' · 周'+['日','一','二','三','四','五','六'][new Date().getDay()];
  }
  for(const k of ['daily','weekly']){
    const warning=document.createElement('div');warning.id=k+'-warnings';warning.className='report-warnings';warning.hidden=true;$('.report-paper',$('[data-page-scope="'+k+'"]')).after(warning);
    const guidance=document.createElement('div');guidance.id=k+'-setup-guidance';guidance.className='setup-guidance';guidance.hidden=true;guidance.innerHTML='<span class="setup-guidance-label"></span> <button type="button" data-setup-mode="profile">完善个人信息</button> <button type="button" data-setup-mode="api">配置模型服务</button>';$('#'+k+'-form').prepend(guidance);
  }
  const sourceHint=document.createElement('p');sourceHint.id='weekly-source-hint';sourceHint.className='weekly-source-hint';sourceHint.hidden=true;sourceHint.innerHTML='本周还没有已保存的日报，保存日报后即可生成周报。 <button type="button" data-route="daily">去写日报</button>';$('#weekly-generate').closest('.generate-area').before(sourceHint);$('#weekly-generate').setAttribute('aria-describedby','weekly-source-hint');
  const historyMore=document.createElement('button');historyMore.id='history-more';historyMore.className='btn';historyMore.type='button';historyMore.textContent='加载更多汇报';historyMore.hidden=true;historyMore.dataset.antComponent='Button';historyMore.style.marginTop='16px';$('#history-list').after(historyMore);historyMore.onclick=()=>loadHistory(false);
  const testModel=document.createElement('button');testModel.id='test-model';testModel.className='btn';testModel.type='button';testModel.textContent='测试已保存配置';testModel.dataset.antComponent='Button';$('#save-settings').before(testModel);
  const clearModelKey=document.createElement('button');clearModelKey.id='clear-model-key';clearModelKey.className='btn';clearModelKey.type='button';clearModelKey.textContent='清除已保存的 Key';clearModelKey.hidden=true;$('#save-settings').before(clearModelKey);
  clearModelKey.onclick=async()=>{
    if(settingsBusy||operationBusy())return;
    settingsBusy=true;syncSettingsActions();
    try{modelConfig=adaptModel(await api('/model-settings/key',{method:'DELETE'}));$('#model-api-key').value='';updateKeyHint();syncAccount();message('已清除 API Key，模型名称和地址已保留。');}
    catch(e){message(e.message,true);}finally{settingsBusy=false;syncSettingsActions();}
  };
  testModel.onclick=async()=>{if(settingsBusy)return;settingsBusy=true;syncSettingsActions();testModel.textContent='正在测试…';try{const result=await api('/model-settings/test',{method:'POST'});message(result.message);}catch(e){message(e.message,true);}finally{settingsBusy=false;syncSettingsActions();testModel.textContent='测试已保存配置';if(!settingsModal.hidden)testModel.focus();}};
  syncAccount();
  init();
})();
