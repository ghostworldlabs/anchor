/* Same provider state and controls in Setup and Cave. Reads never launch work. */
(function () {
  'use strict';
  const labels = {claude:'Claude',chatgpt:'ChatGPT',gemini:'Gemini',grok:'Grok'};
  const request = async (path, body) => {
    const response = await fetch(path, {method:body ? 'POST' : 'GET',credentials:'same-origin',cache:'no-store',
      headers:body ? {'Content-Type':'application/json'} : {'Accept':'application/json'},body:body ? JSON.stringify(body) : undefined});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Host provider settings are unavailable');
    return data;
  };
  function option(select, value, text, disabled) {
    const element = document.createElement('option'); element.value=value; element.textContent=text; element.disabled=!!disabled; select.append(element);
  }
  function selected(data, family, identity) {
    return data.connections.find(c => c.id === (identity || data.preferences.accounts[family] || family+'-default'));
  }
  function capacityText(account) {
    if (!account) return 'Unknown · select an account';
    const allowance = account.allowance;
    if (!allowance.windows.length) return account.auth.replaceAll('_',' ')+' · allowance '+allowance.state+' · Not reported';
    return allowance.state+' · '+allowance.windows.map(w=>w.label+': '+Math.round(w.remaining_percent*10)/10+'% remaining'+(w.resets_at ? ' · resets '+new Date(w.resets_at*1000).toLocaleString() : ' · reset Not reported')).join(' · ');
  }
  function quality(selects, account, choice) {
    const model=selects.model, effort=selects.effort;
    model.replaceChildren(); option(model,'latest_supported','Current frontier');
    (account && account.catalog.state==='fresh' ? account.catalog.rows : []).forEach(row=>option(model,row.model,row.model));
    if(choice && !Array.from(model.options).some(o=>o.value===choice.model))option(model,choice.model,choice.model+' · unavailable',true);
    model.value=choice && choice.model || 'latest_supported'; if(!model.value)model.value='latest_supported';
    effort.replaceChildren();
    function efforts() {
      const prior=effort.value || choice && choice.effort || 'highest_supported'; effort.replaceChildren(); option(effort,'highest_supported','Maximum supported');
      const rows=account ? account.catalog.rows : [], id=model.value==='latest_supported' ? account && account.catalog.selection && account.catalog.selection.model : model.value;
      const row=rows.find(r=>r.model===id); if(row && account.catalog.state==='fresh')row.efforts.forEach(value=>option(effort,value,value));
      if(!Array.from(effort.options).some(o=>o.value===prior))option(effort,prior,prior+' · unavailable',true);
      effort.value=prior; if(!effort.value)effort.value='highest_supported';
    }
    efforts(); model.onchange=efforts;
  }
  function controls(data, prefix, onChange) {
    const family=document.getElementById(prefix+'family'), account=document.getElementById(prefix+'account'), model=document.getElementById(prefix+'model'), effort=document.getElementById(prefix+'effort');
    let draft=JSON.parse(JSON.stringify(data.preferences));
    family.replaceChildren(); Object.keys(labels).forEach(value=>option(family,value,labels[value])); family.value=draft.family || data.default_family;
    function accounts() {
      const f=family.value; account.replaceChildren(); data.connections.filter(c=>c.family===f).forEach(c=>option(account,c.id,c.name+' · '+(c.mode==='api' ? 'API · execution unready' : c.execution.ready ? 'native subscription' : 'execution unready'),c.mode==='api'));
      account.value=draft.accounts[f] || f+'-default'; if(!account.value)account.selectedIndex=0;
      qualities();
    }
    function qualities(){ const c=selected(data,family.value,account.value); quality({model,effort},c,draft.quality[family.value]); if(onChange)onChange(c); }
    family.onchange=accounts; account.onchange=qualities; accounts();
    return {get:()=>({...draft,family:family.value,accounts:{...draft.accounts,[family.value]:account.value},quality:{...draft.quality,[family.value]:{model:model.value,effort:effort.value}}})};
  }
  window.AnchorProviders={request,labels,selected,capacityText,controls};
  if(!document.getElementById('cave-provider-controls')) return;
  let data, controller, opening=null, dialog;
  const gear=document.getElementById('setup-gear'), railHead=document.querySelector('.provider-rail-head'), title=document.querySelector('.masthead .mh-title');
  const narrow=matchMedia('(max-width:760px)');
  function placeGear(){(narrow.matches && title ? title : railHead).prepend(gear);}
  narrow.addEventListener('change',placeGear);placeGear();
  const message=document.getElementById('cave-provider-message');
  function paint(value){
    if(data && value.settings_revision < data.settings_revision)return;
    const preferences=data && controller && value.settings_revision===data.settings_revision ? controller.get() : value.preferences;
    data=value;controller=controls({...data,preferences},'cave-',()=>{});
    const account=selected(data,data.preferences.family || data.default_family), cap=document.getElementById('cave-provider-capacity');
    cap.className='provider-capacity '+(account ? account.capacity : 'unknown');
    cap.querySelector('strong').textContent=account ? labels[account.family]+' · '+account.name : 'Provider capacity';
    cap.querySelector('span').textContent=capacityText(account)+(account && account.warning ? ' · '+account.warning : '');
  }
  async function load(){try{paint(await request('/api/provider-setup'));message.textContent='Apply affects new work; conversations keep their source.';}catch(error){message.textContent=error.message;}}
  function close(){if(dialog && dialog.open){dialog.close();if(opening)opening.focus();load();}}
  function open(from){
    opening=from;
    if(!dialog){dialog=document.createElement('dialog');dialog.className='provider-dialog';dialog.setAttribute('aria-label','Setup settings');const iframe=document.createElement('iframe');iframe.title='Anchor Setup settings';iframe.src='/setup?embed=1';dialog.append(iframe);document.body.append(dialog);dialog.addEventListener('cancel',()=>{if(opening)opening.focus();load();});}
    dialog.showModal();
  }
  document.getElementById('setup-gear').addEventListener('click',e=>open(e.currentTarget));
  document.getElementById('cave-provider-capacity').addEventListener('click',e=>open(e.currentTarget));
  document.getElementById('cave-provider-settings').addEventListener('click',e=>open(e.currentTarget));
  document.getElementById('cave-provider-apply').addEventListener('click',async()=>{
    if(!controller)return;try{paint(await request('/api/provider-setup/apply',{preferences:controller.get(),expected_revision:data.settings_revision}));message.textContent='Saved for new work. Existing conversations retain their source.';}catch(error){message.textContent=error.message;}
  });
  window.addEventListener('message',event=>{if(event.origin!==location.origin || !dialog || event.source!==dialog.querySelector('iframe').contentWindow)return;if(event.data && event.data.type==='anchor-setup-close')close();if(event.data && event.data.type==='anchor-setup-saved')load();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  setInterval(()=>{if(!document.hidden)load();},60000);load();
})();
