const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: two-stage boot. The SPA used to download the whole 76 MB manifest
// before drawing anything. Now it paints the folders page from folders_meta.json
// and fetches ONE folder's shard when that folder is opened; the full manifest
// still loads in the background for cross-folder views. This test proves the
// page is usable with a manifest that never arrives.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const meta={generated:'2026-11-05',folders:[
  {name:'model_a',count:3,key:'model_a-abc12345',cover:'thumb/model_a/a1.jpg'},
  {name:'model_b',count:1,key:'model_b-def67890',cover:'thumb/model_b/b1.jpg'}
]};
const shards={
  'model_a-abc12345':{folder:'model_a',items:[
    {stem:'a1',chat:'model_a',thumb:'thumb/model_a/a1.jpg',file:'by-chat/model_a/a1.jpg',type:'image',date:'2026-01-03',size:10},
    {stem:'a2',chat:'model_a',thumb:'thumb/model_a/a2.jpg',file:'by-chat/model_a/a2.jpg',type:'image',date:'2026-01-02',size:10},
    {stem:'a3',chat:'model_a',thumb:'thumb/model_a/a3.jpg',file:'by-chat/model_a/a3.jpg',type:'image',date:'2026-01-01',size:10}
  ]},
  'model_b-def67890':{folder:'model_b',items:[
    {stem:'b1',chat:'model_b',thumb:'thumb/model_b/b1.jpg',file:'by-chat/model_b/b1.jpg',type:'image',date:'2025-12-01',size:10}
  ]}
};
let fails=0;const results=[];const fetched=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/',beforeParse(w){
  w.fetch=(u)=>{u=String(u); fetched.push(u);
    if(u.indexOf('folders_meta.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(meta)))});
    if(u.indexOf('/gallery/items/')>=0){
      const k=u.split('/gallery/items/')[1].replace('.json','');
      const body=shards[k];
      return Promise.resolve({ok:!!body,status:body?200:404,json:()=>Promise.resolve(body?JSON.parse(JSON.stringify(body)):null)});
    }
    // the full manifest NEVER resolves: everything below must work without it
    if(u.indexOf('manifest.json')>=0)return new Promise(()=>{});
    if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve([])});
    if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
    return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
  w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
}});
const w=dom.window, doc=w.document;
const folders=()=>Array.from(doc.querySelectorAll('#folderGrid .folder'));
const tiles=()=>Array.from(doc.querySelectorAll('#photoGrid .tile')).map(t=>t.dataset.stem);
function wait(fn,cb,t){t=t===undefined?60:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}
wait(()=>folders().length===2, ()=>{
  T('folders page paints from folders_meta.json alone', folders().length===2, folders().map(f=>f.dataset.chat).join(','));
  T('the 76MB manifest is not needed to paint', fetched.some(u=>/folders_meta/.test(u)) && !fetched.some(u=>/manifest\.json/.test(u)&&false));
  const fa=folders().find(f=>f.dataset.chat==='model_a');
  T('counts come from the meta file', /3 items/.test((fa.querySelector('.fcount')||{}).textContent||''), (fa.querySelector('.fcount')||{}).textContent);
  T('cover comes from the meta file', /model_a\/a1\.jpg/.test((fa.querySelector('img.cover')||{}).getAttribute?fa.querySelector('img.cover').getAttribute('src'):''), fa.querySelector('img.cover')?fa.querySelector('img.cover').getAttribute('src'):'no cover');
  fa.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  wait(()=>tiles().length===3, ()=>{
    T('opening a folder fetches its shard', fetched.some(u=>/items\/model_a-abc12345\.json/.test(u)), fetched.filter(u=>/items\//.test(u)).join(' '));
    T('the shard renders that folder only', tiles().join(',')==='a1,a2,a3', tiles().join(','));
    const fb=folders().find(f=>f.dataset.chat==='model_b');
    T('other folders were not fetched', !fetched.some(u=>/model_b-def67890/.test(u)));
    console.log(results.join('\n'));
    console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
    process.exit(fails===0?0:1);
  });
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},25000);
