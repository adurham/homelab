const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: cross-folder item search (search.txt index, no 75MB manifest) and
// landing folder sorting by "recently updated" (folders_meta newest date).
const path=require('path');
const HTML=fs.readFileSync(path.resolve(__dirname,'../files/gallery_index.html'),'utf8');
const meta={folders:[
  {name:'big_old',count:900,key:'big_old-a',cover:null,newest:'2021-03-01'},
  {name:'small_new',count:3,key:'small_new-b',cover:null,newest:'2026-11-04'},
  {name:'mid',count:50,key:'mid-c',cover:null,newest:'2024-06-01'}
]};
const searchTxt=['abc_one\tbig_old','zzz_other\tmid','abc_two\tsmall_new','abc_three\tmid'].join('\n');
let fails=0;const results=[];const fetched=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
function makeDom(url,ls){
  return new JSDOM(HTML,{runScripts:'dangerously',resources:'usable',url,beforeParse(w){
    try{ Object.entries(ls||{}).forEach(([k,v])=>w.localStorage.setItem(k,v)); }catch(_){}
    w.fetch=(u)=>{u=String(u); fetched.push(u);
      if(u.indexOf('folders_meta.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(meta)))});
      if(u.indexOf('search.txt')>=0)return Promise.resolve({ok:true,status:200,text:()=>Promise.resolve(searchTxt),json:()=>Promise.resolve(null)});
      if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve([])});
      if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['big_old','small_new','mid'])});
      if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
      if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({groups:[]})});
      return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
    w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
  }});
}
function wait(fn,cb,t){t=t===undefined?80:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}

// --- A: folder sort by recency -------------------------------------------
const a=makeDom('https://gallery.test/',{'gal.fsort.v1':'recent'});
const wa=a.window, da=wa.document;
wait(()=>da.querySelectorAll('#folderGrid .folder').length===3,()=>{
  const order=Array.from(da.querySelectorAll('#folderGrid .folder')).map(f=>f.dataset.chat);
  T('folders sort by recently updated', order[0]==='small_new'&&order[1]==='mid'&&order[2]==='big_old', order.join(','));
  const sel=da.getElementById('folderSort');
  T('folder sort control reflects the mode', sel&&sel.value==='recent', sel&&sel.value);

  // --- B: global item search ---------------------------------------------
  const b=makeDom('https://gallery.test/#q=abc',{});
  const wb=b.window, db=wb.document;
  wait(()=>db.querySelectorAll('#dupView .gs-row').length>0,()=>{
    const rows=Array.from(db.querySelectorAll('#dupView .gs-row'));
    T('global search renders item rows', rows.length===3, rows.length+' rows');
    T('rows carry folder / stem', /big_old /, rows.map(r=>r.textContent).join('|'));
    T('global search does not need the manifest', !fetched.some(u=>/manifest\.json/.test(u)), 'no manifest fetch');
    T('search index is fetched once', fetched.filter(u=>/search\.txt/.test(u)).length===1, fetched.filter(u=>/search\.txt/.test(u)).length+'');
    console.log(results.join('\n'));
    console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
    process.exit(fails===0?0:1);
  },60);
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},25000);
