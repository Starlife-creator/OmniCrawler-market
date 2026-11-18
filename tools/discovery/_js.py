# SPDX-License-Identifier: MIT
"""发现页客户端内联脚本（主题切换、列表搜索/标签胶囊/排序筛选、详情页复制 ID）。"""

from __future__ import annotations

_JS_THEME = """
(function(){
  var key='oc-market-theme',modes=['system','light','dark'];
  var labels={system:'主题：跟随系统',light:'主题：浅色',dark:'主题：深色'};
  var root=document.documentElement,btn=document.getElementById('theme-toggle');
  function read(){try{var v=localStorage.getItem(key);return modes.indexOf(v)>=0?v:'system';}catch(_e){return 'system';}}
  function write(m){try{if(m==='system'){localStorage.removeItem(key);}else{localStorage.setItem(key,m);}}catch(_e){}}
  function sync(m){
    if(m==='light'||m==='dark'){root.setAttribute('data-theme',m);}
    else{root.removeAttribute('data-theme');}
    if(btn){btn.textContent=labels[m]||labels.system;}
  }
  var cur=read();sync(cur);
  if(btn){
    btn.addEventListener('click',function(){
      cur=modes[(modes.indexOf(cur)+1)%modes.length];
      write(cur);sync(cur);
    });
  }
})();
"""

_JS_LIST = """
(function(){
  var q=document.getElementById('q'),kind=document.getElementById('kind'),
      cat=document.getElementById('cat'),sort=document.getElementById('sort'),
      resetBtn=document.getElementById('reset-filters'),
      customTagBtn=document.getElementById('active-custom-tag'),
      live=document.getElementById('live'),nomatch=document.getElementById('nomatch');
  if(!q||!live){return;}
  var cards=[].slice.call(document.querySelectorAll('article.card'));
  var groups=[].slice.call(document.querySelectorAll('section.group[data-kind]'));
  var segTabs=[].slice.call(document.querySelectorAll('[data-kind-tab]'));
  var tagChips=[].slice.call(document.querySelectorAll('[data-tag-chip]'));
  var cardTags=[].slice.call(document.querySelectorAll('[data-card-tag]'));
  var total=cards.length;
  var activeTag='',activeTagLabel='';
  function syncTabs(k){
    segTabs.forEach(function(tab){
      var on=(tab.getAttribute('data-kind-tab')===k);
      tab.classList.toggle('is-active',on);
      tab.setAttribute('aria-selected',on?'true':'false');
    });
  }
  function syncTagChips(t){
    var hitStatic=false;
    tagChips.forEach(function(chip){
      if(chip===customTagBtn){return;}
      var val=chip.getAttribute('data-tag-chip')||'';
      var on=(val===t);
      if(t&&on){hitStatic=true;}
      chip.classList.toggle('is-active',on);
      chip.setAttribute('aria-pressed',on?'true':'false');
    });
    if(customTagBtn){
      if(t&&!hitStatic){
        customTagBtn.setAttribute('data-tag-chip',t);
        customTagBtn.textContent=(activeTagLabel||t)+' ×';
        customTagBtn.hidden=false;
        customTagBtn.classList.add('is-active');
        customTagBtn.setAttribute('aria-pressed','true');
      }else{
        customTagBtn.hidden=true;
        customTagBtn.classList.remove('is-active');
        customTagBtn.setAttribute('aria-pressed','false');
      }
    }
    cardTags.forEach(function(btn){
      var on=Boolean(t&&(btn.getAttribute('data-card-tag')||'')===t);
      btn.classList.toggle('is-active',on);
    });
  }
  function hasTag(el,t){
    if(!t){return true;}
    var raw=el.getAttribute('data-tags')||'[]';
    try{
      var arr=JSON.parse(raw);
      if(Array.isArray(arr)&&arr.indexOf(t)>=0){return true;}
    }catch(_e){}
    return String(el.dataset.category||'').toLowerCase()===t;
  }
  function nums(v){var m=String(v||'').match(/\\d+/g)||[];return m.map(Number);}
  function cmpOrder(a,b){return Number(a.dataset.order)-Number(b.dataset.order);}
  function cmpText(x,y){
    return String(x||'').localeCompare(String(y||''),'zh-CN',{numeric:true,sensitivity:'base'});
  }
  function cmpVersion(a,b){
    var A=nums(a.dataset.version),B=nums(b.dataset.version),i;
    for(i=0;i<Math.max(A.length,B.length);i++){var x=A[i]||0,y=B[i]||0;if(x!==y){return y-x;}}
    return 0;
  }
  function order(list,mode){
    var items=[].slice.call(list.children);
    if(mode==='name'){
      items.sort(function(a,b){return cmpText(a.dataset.name,b.dataset.name)||cmpOrder(a,b);});
    }else if(mode==='category'){
      items.sort(function(a,b){return cmpText(a.dataset.category,b.dataset.category)||cmpText(a.dataset.name,b.dataset.name)||cmpOrder(a,b);});
    }else if(mode==='updated'){
      items.sort(function(a,b){return String(b.dataset.updated||'').localeCompare(String(a.dataset.updated||''))||cmpOrder(a,b);});
    }else if(mode==='version'){
      items.sort(function(a,b){return cmpVersion(a,b)||cmpOrder(a,b);});
    }else{
      items.sort(cmpOrder);
    }
    items.forEach(function(el){list.appendChild(el);});
    return items;
  }
  function syncUrl(needle,k,c,t,s){
    if(!window.history||!history.replaceState){return;}
    var sp=new URLSearchParams();
    if(needle){sp.set('q',q.value.trim());}
    if(k&&k!=='all'){sp.set('kind',k);}
    if(c&&c!=='all'){sp.set('cat',c);}
    if(t){sp.set('tag',t);}
    if(s&&s!=='order'){sp.set('sort',s);}
    var qs=sp.toString();
    var next=location.pathname+(qs?('?'+qs):'')+location.hash;
    try{history.replaceState(null,'',next);}catch(_e){}
  }
  function apply(){
    var needle=q.value.trim().toLowerCase(),k=kind.value,c=cat.value,s=sort.value,shown=0;
    syncTabs(k);
    syncTagChips(activeTag);
    groups.forEach(function(g){
      var list=g.querySelector('.grid');
      if(!list){return;}
      var items=order(list,s),n=0;
      items.forEach(function(el){
        var ok=true;
        if(needle&&String(el.dataset.search||'').indexOf(needle)<0){ok=false;}
        if(ok&&c!=='all'&&el.dataset.category!==c){ok=false;}
        if(ok&&k!=='all'&&el.dataset.kind!==k){ok=false;}
        if(ok&&!hasTag(el,activeTag)){ok=false;}
        el.hidden=!ok;
        if(ok){n++;}
      });
      g.hidden=(n===0);
      var badge=g.querySelector('.count');
      if(badge){badge.textContent=String(n);}
      shown+=n;
    });
    var dirty=Boolean(needle||k!=='all'||c!=='all'||activeTag||s!=='order');
    if(resetBtn){resetBtn.hidden=!dirty;}
    syncUrl(needle,k,c,activeTag,s);
    live.textContent='显示 '+shown+' / '+total;
    nomatch.hidden=(shown!==0);
  }
  function toggleTag(val,label){
    if(!val||activeTag===val){
      activeTag='';activeTagLabel='';
    }else{
      activeTag=val;activeTagLabel=label||val;
    }
    apply();
  }
  segTabs.forEach(function(tab){
    tab.addEventListener('click',function(){
      var target=tab.getAttribute('data-kind-tab')||'all';
      if(kind.value!==target){kind.value=target;apply();}
    });
  });
  tagChips.forEach(function(chip){
    chip.addEventListener('click',function(){
      var val=chip.getAttribute('data-tag-chip')||'';
      var lbl=chip.getAttribute('data-tag-label')||val;
      toggleTag(val,lbl);
    });
  });
  cardTags.forEach(function(btn){
    btn.addEventListener('click',function(){
      var val=btn.getAttribute('data-card-tag')||'';
      toggleTag(val,btn.textContent||val);
    });
  });
  [q,kind,cat,sort].forEach(function(el){
    el.addEventListener('input',apply);
    el.addEventListener('change',apply);
  });
  if(resetBtn){
    resetBtn.addEventListener('click',function(){
      q.value='';kind.value='all';cat.value='all';activeTag='';activeTagLabel='';sort.value='order';
      apply();q.focus();
    });
  }
  document.addEventListener('keydown',function(ev){
    if(ev.key==='/'&&!ev.ctrlKey&&!ev.metaKey&&!ev.altKey){
      var active=document.activeElement;
      var tag=active&&active.tagName?active.tagName.toUpperCase():'';
      if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT'||(active&&active.isContentEditable)){return;}
      ev.preventDefault();q.focus();if(q.select){q.select();}
    }else if(ev.key==='Escape'&&document.activeElement===q&&q.value){
      q.value='';apply();
    }
  });
  var params=new URLSearchParams(location.search);
  var initQ=params.get('q');
  if(initQ){q.value=initQ;}
  ['kind','cat','sort'].forEach(function(key){
    var value=params.get(key),el=document.getElementById(key);
    if(!value||!el){return;}
    var exists=[].some.call(el.options||[],function(opt){return opt.value===value;});
    if(exists){el.value=value;}
  });
  var initTag=(params.get('tag')||'').trim().toLowerCase();
  if(initTag){activeTag=initTag;activeTagLabel=params.get('tag').trim();}
  apply();
})();
"""

_JS_DETAIL = """
(function(){
  document.querySelectorAll('[data-copy]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var value=btn.getAttribute('data-copy')||'',label=btn.textContent;
      function done(ok){
        btn.textContent=ok?'已复制':'已选中，请按 Ctrl/Cmd+C';
        setTimeout(function(){btn.textContent=label;},1600);
      }
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(value).then(function(){done(true);},function(){done(false);});
      }else{
        done(false);
      }
    });
  });
})();
"""
