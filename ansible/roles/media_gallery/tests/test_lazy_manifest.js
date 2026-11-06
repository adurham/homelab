const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: the 75MB manifest must NOT be fetched for ordinary browsing.
// Two-stage boot paints folders from folders_meta.json and a folder from its
// shard; only the duplicate view needs every item, so only #dup may request
// the manifest.
const path=require('path');
const HTML=fs.readFileSync(path.resolve(__dirname,'../files/gallery_index.html'),'utf8');
const meta={folders:[{name:'model_a',count:2,key:'model_a-abc',cover:'thumb/model_a/a1.jpg'}]};
const shard={folder:'model_a',items:[
  {stem:'a1',chat:'model_a',thumb:'thumb/model_a/a1.jpg',file:'by-chat/model_a/a1.jpg',type:'image',date:'2026-01-02',size:10},
  {stem:'a2',chat:'model_a',thumb:'thumb/model_a/a2.jpg',file:'by-chat/model_a/a2.jpg',type:'image',date:'2026-01-01',size:10}
]};
let fails=0;const results=[];const fetched=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
function makeDom(startUrl){
  return new JSDOM(HTML,{runScripts:'dangerously',resources:'usable',url:startUrl,beforeParse(w){
    w.fetch=(u)=>{u=String(u); fetched.push(u);
      if(u.indexOf('folders_meta.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(meta)))});
      if(u.indexOf('/gallery/items/')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(shard)))});
      if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve([
        {stem:'a1',chat:'model_a',thumb:'thumb/model_a/a1.jpg',file:'by-chat/model_a/a1.jpg',type:'image',date:'2026-01-02',size:10},
        {stem:'a2',chat:'model_a',thumb:'thumb/model_a/a2.jpg',file:'by-chat/model_a/a2.jpg',type:'image',date:'2026-01-01',size:10}])});
      if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({groups:[]})});
      if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['model_a'])});
      if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
      return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
    w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
  }});
}
function wait(fn,cb,t){t=t===undefined?80:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}
const hadManifest=()=>fetched.some(u=>/manifest\.json/.test(u));

const dom=makeDom('https://gallery.test/');
const w=dom.window,doc=w.document;
wait(()=>doc.querySelectorAll('#folderGrid .folder').length>0,()=>{
  T('folders page paints', doc.querySelectorAll('#folderGrid .folder').length===1);
  doc.querySelector('#folderGrid .folder[data-chat="model_a"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  wait(()=>doc.querySelectorAll('#photoGrid .tile').length>0,()=>{
    T('folder opens from its shard', doc.querySelectorAll('#photoGrid .tile').length===2);
    T('the full manifest is NOT fetched for normal browsing', !hadManifest(), fetched.filter(u=>/manifest/.test(u)).join(' ')||'none');
    // now the duplicate view, which is the one that needs every item
    const dom2=makeDom('https://gallery.test/#dup');
    wait(()=>hadManifest(),()=>{
      T('#dup DOES load the manifest', hadManifest(), fetched.filter(u=>/manifest/.test(u)).length+' fetch(es)');
      console.log(results.join('\n'));
      console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
      process.exit(fails===0?0:1);
    },40);
  });
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},25000);
