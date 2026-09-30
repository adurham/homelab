const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-09-30: guards the reported "page crashed on search".
// Before the DOM render cap, a broad query ("a" matches every stem) selected
// all ~278K manifest items and renderPhotos() built a DOM subtree per item —
// reproduced as an out-of-memory process death. The cap pages the DOM while
// keeping the full match set in `shown`, and a "Show more" sentinel makes the
// truncation explicit. This test loads a 278K-item manifest, searches, and
// asserts the render stays bounded and the affordance works.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const N=278607;
const manifest=[];
for(let i=0;i<N;i++) manifest.push({stem:'q_'+i,chat:'c'+(i%20),thumb:'thumb/x/q_'+i+'.jpg',file:'by-chat/x/q_'+i+'.jpg',type:'image',date:'2026-01-01',size:1000});
let fails=0;const results=[];
function T(name,cond,detail){ results.push((cond?'PASS':'FAIL')+'  '+name+(detail?('   ['+detail+']'):'')); if(!cond)fails++; }
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve([])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('trashqueue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(null)});
   return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
setTimeout(()=>{
  const sb=doc.getElementById('searchBox');
  sb.value='q_';
  const t0=Date.now();
  sb.dispatchEvent(new window.Event('input',{bubbles:true}));
  setTimeout(()=>{
    const tiles=doc.querySelectorAll('#photoGrid .tile').length;
    const more=doc.querySelector('.showmore');
    T('broad search does not blow up the DOM', tiles>0 && tiles<=2000, tiles+' tiles');
    T('render stays bounded well under the match count', tiles<N/10, `${tiles} tiles for ${N} matches`);
    T('Show-more affordance present', !!more, more?more.textContent.slice(0,50):'(none)');
    if(more){
      more.dispatchEvent(new window.MouseEvent('click',{bubbles:true}));
      setTimeout(()=>{
        const t2=doc.querySelectorAll('#photoGrid .tile').length;
        T('Show more increases the rendered page', t2>tiles, `${tiles} -> ${t2}`);
        T('sub count still reflects the FULL match set', /278,?607/.test(doc.getElementById('sub').textContent||''), doc.getElementById('sub').textContent);
        console.log(results.join('\n'));
        console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
        process.exit(fails===0?0:1);
      },500);
    }else{
      console.log(results.join('\n')); console.log(fails+' FAILURES'); process.exit(1);
    }
  },400);
},3000);
setTimeout(()=>{ console.log('TIMEOUT — render never completed (the crash)'); console.log(results.join('\n')); process.exit(2); },60000);
