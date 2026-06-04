const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[{stem:'a1',chat:'person3',thumb:'thumb/person3/a1.jpg',file:'f',type:'image',date:'2026-01-03',size:100}];
const dedup={generated:'2026-06-04',hamming:6,scanned:3,dup_groups:1,dup_items:3,
 groups:[[{stem:'a1',chat:'person3',thumb:'thumb/person3/a1.jpg',file:'f',size:100,date:'2026-01-03'},
          {stem:'a2',chat:'person3',thumb:'thumb/person3/a2.jpg',file:'f',size:100,date:'2026-01-02'},
          {stem:'a3',chat:'person3',thumb:'thumb/person3/a3.jpg',file:'f',size:100,date:'2026-01-01'}]]};
let trashBody=null;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['person3'])});
   if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(dedup)))});
   if(u.indexOf('/trashbatch')>=0){trashBody=JSON.parse(opts.body);return Promise.resolve({status:200,json:()=>Promise.resolve({deleted:trashBody.stems.length})});}
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 click(doc.getElementById('dedupBtn'));
 setTimeout(()=>{
   var cards=doc.querySelectorAll('.dupcard');
   console.log('cards rendered (3-member group):',cards.length,'(expect 3)', cards.length===3?'PASS':'FAIL');
   var keep=doc.querySelectorAll('.dupcard.keep').length, trash=doc.querySelectorAll('.dupcard.trash').length;
   console.log('default keep:',keep,'trash:',trash,'(expect 1/2)', (keep===1&&trash===2)?'PASS':'FAIL');
   // toggle footer on the keep card -> should become trash
   var keepCard=doc.querySelector('.dupcard.keep'); click(keepCard.querySelector('.dc-toggle'));
   console.log('after toggle keepCard now trash:', keepCard.classList.contains('trash')?'PASS':'FAIL');
   // reset via group "keep newest only"
   click(doc.querySelector('.dg-mark[data-act="keepfirst"]'));
   click(doc.getElementById('dupTrash'));
   setTimeout(()=>{
     console.log('trashbatch:',JSON.stringify(trashBody));
     var ok=trashBody&&trashBody.stems.length===2&&trashBody.stems.indexOf('a1')<0;
     console.log(ok?'PASS trashed 2 older, kept a1':'FAIL');
   },150);
 },200);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);
