const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: bulk duplicate curation. Keep/hide one group at a time across
// hundreds of groups was the last fully-manual chore. Only groups where the
// recommended copy is clearly better (same size within 2%, or >=1.5x) are
// eligible; the rest stay manual. Nothing is deleted — Undo restores.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const manifest=[
  {stem:'a1',chat:'m',thumb:'t/a1.jpg',file:'by-chat/m/a1.jpg',type:'image',date:'2026-01-05',size:100},
  {stem:'a2',chat:'m',thumb:'t/a2.jpg',file:'by-chat/m/a2.jpg',type:'image',date:'2026-01-04',size:100},
  {stem:'b1',chat:'m',thumb:'t/b1.jpg',file:'by-chat/m/b1.jpg',type:'image',date:'2026-01-03',size:300},
  {stem:'b2',chat:'m',thumb:'t/b2.jpg',file:'by-chat/m/b2.jpg',type:'image',date:'2026-01-02',size:200},
  {stem:'c1',chat:'m',thumb:'t/c1.jpg',file:'by-chat/m/c1.jpg',type:'image',date:'2026-01-01',size:100},
  {stem:'c2',chat:'m',thumb:'t/c2.jpg',file:'by-chat/m/c2.jpg',type:'image',date:'2026-01-01',size:90}
];
const dedup={generated:'2026-11-05T00:00:00',hamming:6,scanned:6,groups:[
  [ {stem:'a1',chat:'m',size:100}, {stem:'a2',chat:'m',size:100} ],
  [ {stem:'b1',chat:'m',size:300}, {stem:'b2',chat:'m',size:200} ],
  [ {stem:'c1',chat:'m',size:100}, {stem:'c2',chat:'m',size:90} ]
]};
let fails=0;const results=[];const calls=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/#dup',beforeParse(w){
  w.fetch=(u,o)=>{u=String(u);
    if(u.indexOf('sethidden')>=0){ calls.push(JSON.parse(o.body)); return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({ok:true})}); }
    if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(dedup)))});
    if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
    if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['m'])});
    if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
    return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
  w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
}});
const w=dom.window, doc=w.document;
function wait(fn,cb,t){t=t===undefined?80:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}
wait(()=>doc.querySelectorAll('.dupgroup').length>=3, ()=>{
  const btn=doc.getElementById('dupBulk');
  T('bulk button appears when high-confidence groups exist', !!btn, btn?btn.textContent:'(none)');
  T('it counts only the clearly-better groups', !!btn && /2 groups/.test(btn.textContent), btn&&btn.textContent);
  btn.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  setTimeout(()=>{
    T('bulk action posts the losing copies as hidden', calls.length===1 && Array.isArray(calls[0].stems) && calls[0].stems.sort().join(',')==='a2,b2',
      calls.length?JSON.stringify(calls[0]):'no call');
    T('it asks to hide, never delete', calls.length===1 && calls[0].hidden===true, calls.length?String(calls[0].hidden):'-');
    const und=doc.querySelector('#toast .toast-undo');
    T('an Undo affordance is offered', !!und, und?und.textContent:'(none)');
    und.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
    setTimeout(()=>{
      T('Undo un-hides exactly those copies', calls.length===2 && calls[1].hidden===false && calls[1].stems.sort().join(',')==='a2,b2',
        calls.length>1?JSON.stringify(calls[1]):'no undo call');
      // "not duplicates" on a remaining group persists
      const nd=Array.from(doc.querySelectorAll('.dg-mark')).find(b=>b.dataset.act==='notdup');
      nd.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
      let st=null; try{ st=JSON.parse(w.localStorage.getItem('gal.notdup.v1')||'[]'); }catch(_){}
      T('not-duplicates is remembered', Array.isArray(st) && st.length===1, JSON.stringify(st));
      T('that group disappears from the view', doc.querySelectorAll('.dupgroup').length===2, doc.querySelectorAll('.dupgroup').length+' left');
      console.log(results.join('\n'));
      console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
      process.exit(fails===0?0:1);
    },300);
  },400);
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},30000);
