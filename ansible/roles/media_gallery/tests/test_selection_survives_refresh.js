const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'person_1',file:'by-chat/person_1/a1.jpg',thumb:'thumb/person_1/a1.jpg',type:'image',date:'2026-01-01'},
 {stem:'a2',chat:'person_1',file:'by-chat/person_1/a2.jpg',thumb:'thumb/person_1/a2.jpg',type:'image',date:'2026-01-02'},
 {stem:'a3',chat:'person_1',file:'by-chat/person_1/a3.jpg',thumb:'thumb/person_1/a3.jpg',type:'image',date:'2026-01-03'},
 {stem:'b1',chat:'person_2',file:'by-chat/person_2/b1.jpg',thumb:'thumb/person_2/b1.jpg',type:'image',date:'2026-01-04'},
];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>String(url).indexOf('manifest.json')>=0
   ?Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)})
   :Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});
 window.alert=(m)=>{console.log('ALERT:',m);window.__lastAlert=m;};
 window.confirm=()=>true;window.prompt=()=>'NF';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 let p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person_1')p1=f;});
 click(p1);
 let tiles=doc.querySelectorAll('#photoGrid .tile');
 click(tiles[0].querySelector('.selbox')); click(tiles[1].querySelector('.selbox'));
 console.log('after select: selected tiles=',doc.querySelectorAll('.tile.selected').length,'bulkCount=',doc.getElementById('bulkCount').textContent);

 // Simulate the background reloadManifest that fires after actions / on a timer.
 // It calls openFolder(current) internally. We trigger it by calling the global
 // path the same way the app does. Easiest: re-dispatch sort change which calls openFolder(current).
 console.log('--- simulating a re-render (openFolder via sort change), as reloadManifest/timer would ---');
 const sortSel=doc.getElementById('sort');
 // openFolder(current) is what reloadManifest calls; sort 'change' handler does openFolder(current)
 sortSel.dispatchEvent(new window.Event('change',{bubbles:true}));
 tiles=doc.querySelectorAll('#photoGrid .tile');
 console.log('after re-render: selected tiles=',doc.querySelectorAll('.tile.selected').length,'bulkCount=',doc.getElementById('bulkCount').textContent);

 // now try to move
 window.__lastAlert=null;
 click(doc.getElementById('bulkMove'));
 console.log('bulkMove -> alert:',window.__lastAlert,'| menu shown:',doc.getElementById('bulkMoveMenu').classList.contains('show'));
 if(window.__lastAlert&&/select some items/i.test(window.__lastAlert))
   console.log('>>> BUG REPRODUCED: re-render cleared the selection Set <<<');
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);
