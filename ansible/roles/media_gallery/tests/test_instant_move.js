const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'F1',file:'by-chat/F1/a1.jpg',thumb:'thumb/F1/a1.jpg',type:'image',date:'2026-01-02',size:1},
 {stem:'a2',chat:'F1',file:'by-chat/F1/a2.jpg',thumb:'thumb/F1/a2.jpg',type:'image',date:'2026-01-01',size:1},
 {stem:'b1',chat:'F2',file:'by-chat/F2/b1.jpg',thumb:'thumb/F2/b1.jpg',type:'image',date:'2026-01-03',size:1}];
let markBody=null, batchCalled=false;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F1','F2'])});
   if(u.indexOf('/movemark')>=0){markBody=JSON.parse(opts.body);return Promise.resolve({status:200,json:()=>Promise.resolve({marked:markBody.stems.length,queue_depth:markBody.stems.length})});}
   if(u.indexOf('/movebatch')>=0){batchCalled=true;return Promise.resolve({status:200,json:()=>Promise.resolve({moved:1})});}
   if(u.indexOf('movequeue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:2,moved:0,failed:0})});
   if(u.indexOf('trashqueue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0,reaped:0,failed:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 var p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='F1')p1=f;});
 click(p1);
 var tiles=doc.querySelectorAll('#photoGrid .tile');
 click(tiles[0].querySelector('.selbox')); click(tiles[1].querySelector('.selbox'));
 click(doc.getElementById('bulkMove'));
 var p2=null;doc.querySelectorAll('#bulkMoveMenu button').forEach(b=>{if(b.textContent.indexOf('F2')>=0)p2=b;});
 click(p2);
 setTimeout(()=>{
   var remain=doc.querySelectorAll('#photoGrid .tile').length;
   console.log('F1 tiles immediately after move:',remain,'(expect 0 - instant)', remain===0?'PASS':'FAIL');
   console.log('used /movemark:',!!markBody,'| used /movebatch:',batchCalled, (markBody&&!batchCalled)?'PASS instant':'FAIL');
   console.log('movemark body:',JSON.stringify(markBody));
   // KEY: browse to F2 -> item shows AND its thumb still points to ORIGINAL F1 path
   var f2=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='F2')f2=f;});
   if(f2){ click(f2);
     setTimeout(()=>{
       var f2tiles=doc.querySelectorAll('#photoGrid .tile');
       console.log('F2 tiles after move (b1 + a1,a2 moved in):',f2tiles.length,'(expect 3)', f2tiles.length===3?'PASS':'FAIL');
       // find a moved item's img src -> must still be the ORIGINAL F1 thumb path (not F2)
       var movedImg=null;
       f2tiles.forEach(t=>{ if(t.dataset.stem==='a1'){ movedImg=t.querySelector('img'); } });
       var src=movedImg?movedImg.getAttribute('data-src')||movedImg.getAttribute('src'):'';
       console.log('moved item a1 thumb src:',src);
       console.log(src.indexOf('/F1/')>=0?'PASS thumb still loads from original F1 path':'FAIL thumb points to F2 (would 404)');
       process.exit(0);
     },200);
   }
 },150);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);process.exit(1);} },800);
