const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: the grid is VIRTUAL — only the rows in view live in the DOM, inside
// a sizer whose height is the true height of the whole folder. This replaced the
// 2026-09-30 "1200-tile cap + Show more" page, which chopped a 15,865-item folder
// into 13 artificial pages and gave the scrollbar a lie. The crash that cap
// guarded against (one DOM subtree per matched item, ~278K of them) still cannot
// happen: the DOM is bounded by the viewport, not by the match count.
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
  const first=Array.from(doc.querySelectorAll('#folderGrid .folder'))[0];
  if(!first){ console.log('FAIL  folder grid never rendered'); process.exit(1); }
  first.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));
  const inFolder=manifest.filter(m=>m.chat===first.dataset.chat).length;
  setTimeout(()=>{
    const sb=doc.getElementById('searchBox');
    sb.value='q_';
    sb.dispatchEvent(new window.Event('input',{bubbles:true}));
    setTimeout(()=>{
      const tiles=doc.querySelectorAll('#photoGrid .tile').length;
      const sizer=doc.querySelector('#photoGrid .pgsizer');
      const h=sizer?parseFloat(sizer.style.height):0;
      const idx=Array.from(doc.querySelectorAll('#photoGrid .tile')).map(t=>+t.dataset.i);
      T('broad in-folder search does not blow up the DOM', tiles>0 && tiles<=800, tiles+' tiles');
      T('DOM bounded by the viewport, not the match count', tiles < inFolder/10, `${tiles} tiles for ${inFolder} matches`);
      T('virtual grid renders a sizer for the full folder', !!sizer && h>100000, sizer?('height='+Math.round(h)+'px'):'(no sizer)');
      T('no Show-more paging in the virtual grid', !doc.querySelector('.showmore'));
      T('tiles carry real indices into the match set', idx.length>0 && Math.min.apply(null,idx)===0, 'min='+Math.min.apply(null,idx)+' max='+Math.max.apply(null,idx));
      T('sub count still reflects the FULL match set', new RegExp(inFolder.toLocaleString().replace(/,/g,'')).test((doc.getElementById('sub').textContent||'').replace(/,/g,'')), doc.getElementById('sub').textContent);
      console.log(results.join('\n'));
      console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
      process.exit(fails===0?0:1);
    },800);
  },800);
},3000);
setTimeout(()=>{ console.log('TIMEOUT — render never completed'); console.log(results.join('\n')); process.exit(2); },60000);
