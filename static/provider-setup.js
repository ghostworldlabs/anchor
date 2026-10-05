(function(){
  'use strict';
  const api=window.AnchorProviders,$=id=>document.getElementById(id);
  let data,family='claude',connectionId,controller,login,poll;
  function text(tag,value,className){const node=document.createElement(tag);node.textContent=value;if(className)node.className=className;return node;}
  function button(title,action){const b=text('button',title);b.type='button';b.onclick=()=>Promise.resolve(action()).catch(error=>{$('setup-message').textContent=error.message;$('setup-message').className='error';});return b;}
  function section(name){['host','providers','chart'].forEach(s=>$('setup-section-'+s).hidden=s!==name);document.querySelectorAll('.setup-steps [data-section]').forEach(b=>{if(b.dataset.section===name)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});}
  function leave(){if(window.parent!==window)window.parent.postMessage({type:'anchor-setup-close'},location.origin);else location.href='/high-seat';}
  function active(){return data.connections.find(c=>c.id===connectionId) || data.connections.find(c=>c.family===family);}
  function reportFacts(parent,account){
    const facts=document.createElement('dl');facts.className='provider-facts';
    const rows=[['Native sign-in',account.auth.replaceAll('_',' ')+(account.auth_stale?' · stale':'')],['Connection test',account.test+' · status/account command only'],
      ['Subscription allowance',api.capacityText(account)],['Allowance source / observed',account.allowance.source+' · '+(account.allowance.observed_at || 'Not reported')],
      ['Exact tokens remaining','Not reported'],['Provider account token activity',account.provider_usage.tokens===null ? 'Not reported · '+account.provider_usage.state : account.provider_usage.tokens.toLocaleString()+' lifetime tokens · '+account.provider_usage.state],
      ['Token activity source / observed',account.provider_usage.source+' · '+(account.provider_usage.observed_at || 'Not reported')],
      ['Anchor-observed consumption',account.anchor_observed.tokens===null ? 'Not reported; legacy observations have no account attribution' : account.anchor_observed.tokens.toLocaleString()+' tokens · '+account.anchor_observed.period],
      ['Anchor source / observed',account.anchor_observed.source+' · '+(account.anchor_observed.observed_at || 'Not reported')],
      ['API spend','Not reported · '+account.api_spend.state],['Subscription price','Not reported · '+account.subscription_price.state]];
    rows.forEach(([label,value])=>{const cell=document.createElement('div');cell.append(text('dt',label),text('dd',value));facts.append(cell);});parent.append(facts);
    account.allowance.windows.forEach(w=>{parent.append(text('p',w.label+' · '+w.remaining_percent+'% remaining'+(account.allowance.state==='stale'?' · stale':'')));const meter=document.createElement('div');meter.className='provider-meter';const fill=document.createElement('span');fill.style.width=w.remaining_percent+'%';meter.append(fill);parent.append(meter);});
    if(account.warning)parent.append(text('p',account.warning,'setup-notice near_limit'));
    if(account.allowance.state==='stale')parent.append(text('p','Stale report retained. Refresh on the host before treating it as current capacity.','setup-notice stale'));
  }
  function drawAccounts(){
    $('provider-tabs').replaceChildren();Object.entries(api.labels).forEach(([key,label])=>{const b=button(label,()=>{family=key;connectionId=null;drawAccounts();drawDetail();});b.setAttribute('aria-pressed',String(key===family));$('provider-tabs').append(b);});
    const account=active();if(account)connectionId=account.id;
    $('provider-accounts').replaceChildren();data.connections.filter(c=>c.family===family).forEach(c=>{const b=button(c.name,()=>{connectionId=c.id;drawAccounts();drawDetail();});b.className='provider-account';b.setAttribute('aria-pressed',String(c.id===connectionId));b.append(text('span',c.mode+' · '+c.auth.replaceAll('_',' ')+' · allowance '+c.allowance.state));$('provider-accounts').append(b);});
    const cap=account && account.capability;
    $('add-account-limit').textContent=cap && !cap.isolated ? cap.limit || 'This installed CLI cannot verify isolated subscription homes. Optional API mode is separate and unready for execution.' : 'A second subscription uses a separate native home. The existing default is never overwritten.';
    $('add-account').disabled=$('new-account-mode').value==='subscription' && (!cap || !cap.isolated);
  }
  function drawDetail(){
    const c=active(),detail=$('provider-detail');detail.replaceChildren();if(!c)return;
    detail.append(text('h2',api.labels[c.family]+' · '+c.name),text('p','Runs on '+data.host.name+' · '+c.mode+' mode · '+(c.capability.installed?'CLI installed':'CLI unavailable')+' · version '+(c.capability.version||'Not reported')));
    if(c.capability.limit)detail.append(text('p',c.capability.limit,'setup-notice'));
    detail.append(text('p',c.execution.reason,'muted'));
    const label=text('label','Connection nickname');label.htmlFor='account-nickname';const nickname=document.createElement('input');nickname.id='account-nickname';nickname.value=c.name;nickname.maxLength=70;
    detail.append(label,nickname,button('Save nickname',async()=>{render(await api.request('/api/provider-setup/rename',{connection_id:c.id,name:nickname.value,expected_revision:data.settings_revision}));}));
    const actions=document.createElement('div');actions.className='setup-actions';
    actions.append(button('Refresh / test this account on host',()=>refresh(c.id)));
    if(c.mode==='subscription'){
      const sign=button('Sign in on mother ship',async()=>{login=await api.request('/api/provider-setup/login',{connection_id:c.id});drawLogin();scheduleLogin();});
      sign.disabled=c.native_default || !c.capability.login || !c.capability.isolated || c.auth==='signed_in';actions.append(sign);
      if(c.native_default)detail.append(text('p','Existing native sign-in is retained. To enroll another subscription, add a named connection first. No open terminal is needed for a persisted login.','small muted'));
    }else{
      detail.append(text('p','API mode has separate billing. Credentials are stored in the host OS vault. Its model catalog test submits no model work. Execution remains unready.','setup-notice'));
      if(data.client_can_enter_api && data.api_storage_available){
        const l=text('label','API key · secure host storage');l.htmlFor='api-key';const input=document.createElement('input');input.id='api-key';input.type='password';input.autocomplete='off';
        detail.append(l,input,button('Validate & save API credential on host',async()=>{const key=input.value;input.value='';render(await api.request('/api/provider-setup/api-key',{connection_id:c.id,api_key:key}));}));
      }else detail.append(text('p','Enter API credentials in Setup on the mother ship itself. Secure storage must be available.','muted'));
    }
    detail.append(actions);reportFacts(detail,c);const panel=document.createElement('div');panel.id='login-progress';detail.append(panel);drawLogin();
  }
  function drawLogin(){const box=$('login-progress');if(!box || !login || login.connection_id!==connectionId)return;box.replaceChildren(text('p',login.message,'setup-notice'));
    if(login.url){const link=text('a','Open native sign-in');link.href=login.url;link.target='_blank';link.rel='noopener noreferrer';box.append(link);}
    if(login.user_code)box.append(text('p','Native device code: '+login.user_code));
    if(['starting','awaiting_browser','cancelling'].includes(login.state)){box.append(text('p','This attempt expires at '+new Date(login.expires_at*1000).toLocaleTimeString()));const cancel=button('Cancel sign-in',async()=>{login=await api.request('/api/provider-setup/cancel',{id:login.id});drawLogin();});cancel.disabled=login.state==='cancelling';box.append(cancel);}
  }
  function scheduleLogin(){clearTimeout(poll);if(!login || !['starting','awaiting_browser','cancelling'].includes(login.state))return;poll=setTimeout(async()=>{try{login=await api.request('/api/provider-setup/login?id='+encodeURIComponent(login.id));drawLogin();if(login.state==='completed')render(await api.request('/api/provider-setup'));scheduleLogin();}catch(error){$('setup-message').textContent=error.message;}},1000);}
  function render(value){
    if(data && value.settings_revision<data.settings_revision)return;
    data=value;const first=!connectionId;family=first ? value.preferences.family || value.default_family : family;
    $('setup-host').textContent=value.host.name+' · mother ship';$('provider-host-note').textContent='All actions run on '+value.host.name+'. This browser is the host’s interface. Authentication and capacity are separate facts.';
    $('host-runtime').textContent='Connected runtime: '+value.host.name+' · '+(value.host.configured?'existing setup retained':'first setup')+' · data directory '+value.host.data_directory;
    $('host-network').textContent=value.host.tailscale;$('setup-project-roots').replaceChildren();value.host.project_roots.forEach(root=>$('setup-project-roots').append(text('li',root)));
    $('setup-initialize').hidden=!value.host.first_setup;
    if(!value.host.project_roots.length)$('setup-project-roots').append(text('li','No configured project folders were reported. Choose the first storage location with Aladdin in Star Chart.'));
    if(value.host.star_chart_url)$('setup-star-chart').href=value.host.star_chart_url;
    drawAccounts();drawDetail();controller=api.controls(data,'setup-',()=>{});$('setup-threshold').value=String(data.preferences.warning_threshold);$('setup-warning').value=data.preferences.warning_policy;
    if(data.settings_error)$('setup-message').textContent=data.settings_error;
  }
  async function refresh(id){$('provider-refresh').disabled=true;$('refresh-message').textContent='Reading native status and account reports on the mother ship…';try{render(await api.request('/api/provider-setup?refresh=1'+(id?'&connection_id='+encodeURIComponent(id):'')));$('refresh-message').textContent='Host reads completed; unsupported reports remain explicit.';}finally{$('provider-refresh').disabled=false;}}
  document.querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>section(b.dataset.section));
  $('setup-return').onclick=leave;$('chart-return').onclick=leave;$('new-account-mode').onchange=drawAccounts;
  $('provider-refresh').onclick=()=>refresh().catch(error=>$('setup-message').textContent=error.message);
  $('setup-initialize').onclick=async()=>{try{render(await api.request('/api/provider-setup/initialize',{expected_revision:data.settings_revision}));$('initialize-message').textContent='Setup saved with Aladdin. Existing installation and folders retained.';section('providers');}catch(error){$('initialize-message').textContent=error.message;}};
  $('add-account-form').onsubmit=async event=>{event.preventDefault();try{const result=await api.request('/api/provider-setup/accounts',{family,name:$('new-account-name').value,mode:$('new-account-mode').value,expected_revision:data.settings_revision});connectionId=result.connection_id;render(result.snapshot);$('new-account-name').value='';}catch(error){$('setup-message').textContent=error.message;}};
  $('setup-apply').onclick=async()=>{$('setup-apply').disabled=true;$('apply-message').textContent='Saving…';try{const prefs=controller.get();prefs.warning_threshold=Number($('setup-threshold').value);prefs.warning_policy=$('setup-warning').value;render(await api.request('/api/provider-setup/apply',{preferences:prefs,expected_revision:data.settings_revision}));$('apply-message').textContent='Saved for new work. Existing conversations retain their accounts and sessions.';if(window.parent!==window)window.parent.postMessage({type:'anchor-setup-saved'},location.origin);}catch(error){$('apply-message').textContent=error.message;}finally{$('setup-apply').disabled=false;}};
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();leave();}});
  api.request('/api/provider-setup').then(value=>{render(value);section(value.host.configured?'providers':'host');}).catch(error=>$('setup-message').textContent=error.message);
})();
