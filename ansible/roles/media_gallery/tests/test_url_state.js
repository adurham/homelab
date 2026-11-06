const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: a deep link must restore the whole in-folder UI state — query,
// type/year/size/unseen filters — and the open lightbox item must appear in the
// hash so a link points at a specific image.
const path=require('path');
const HTML=fs.readFileSync(path.resolve(__dirname,'../files/gallery_index.html'),'utf8');
const meta={folders:[{name:'model_a',count:2,key:'model_a-abc',cover:null,newest:'2026-01-02'}]};
const shard={folder:'model_a',items:[
  {stem:'pic1',chat:'model_a',thumb:'thumb/model_a/pic1.jpg',file:'by-chat/model_a/pic1.jpg',type:'image',date:'2026-01-02',size:10},
  {stem:'clip1',chat:'model_a',thumb:'thumb/model_a/clip1.jpg',file:'by-chat/model_a/clip1.mp4',type:'video',date:'2026-01-01',size:20}
]};
let fails=0;const results=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
const dom=new JSDOM(HTML,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/#f=model_a&t=video&u=1',beforeParse(w){
  w.fetch=(u)=>{u=String(u);
    if(u.indexOf('folders_meta.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(meta)))});
    if(u.indexOf('/gallery/items/')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(shard)))});
    if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve([])});
    if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['model_a'])});
    if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
    return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
  w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
}});
const w=dom.window,doc=w.document;
function wait(fn,cb,t){t=t===undefined?80:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}
wait(()=>doc.querySelectorAll('#photoGrid .tile').length>0,()=>{
  const tiles=Array.from(doc.querySelectorAll('#photoGrid .tile')).map(t=>t.dataset.stem);
  T('deep link restores the type filter', tiles.join(',')==='clip1', tiles.join(',')||'none');
  // opening a lightbox should add the item stem to the hash, alongside the
  // filters that came from the deep link
  const t0=doc.querySelector('#photoGrid .tile');
  t0.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  wait(()=>/i=clip1/.test(w.location.hash),()=>{
    T('opening an item puts its stem in the hash', /i=clip1/.test(w.location.hash), w.location.hash);
    T('the restored filters are in the hash too', /t=video/.test(w.location.hash)&&/u=1/.test(w.location.hash), w.location.hash);
    console.log(results.join('\n'));
    console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
    process.exit(fails===0?0:1);
  },30);
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},25000);
