const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// Regression test for the 2026-09-12 fix: a dedup.json report can be stale
// (only regenerated periodically) and list a stem that was ALREADY deleted
// since the report was generated -- by this browser tab, another tab, or a
// scheduled scan lagging behind manual deletes. Real user report: "when I
// clicked delete it never deleted it" -- the delete had actually already
// succeeded; the stale report just kept showing the (now-gone) file as if
// it were still a live duplicate, forever, because nothing ever
// cross-checked the report against what's actually still in the gallery.
//
// manifest here is the CURRENT live truth: only 'a1' and 'a3' still exist.
// dedup.json (stale) has ONE group of 3: a1, a2, a3 -- 'a2' was deleted
// after this report was generated and must be silently dropped, leaving a
// still-valid 2-member group (a1, a3), NOT rendered as if a2 still existed.
const manifest=[
  {stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',type:'image',date:'2026-01-03',size:1},
  {stem:'a3',chat:'F',thumb:'thumb/F/a3.jpg',file:'f',type:'image',date:'2026-01-01',size:1}
  // NOTE: 'a2' intentionally absent -- simulates an already-completed delete
];
const dedup={generated:'2026-06-04',hamming:6,scanned:3,dup_groups:1,dup_items:3,
 groups:[[{stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',size:1,date:'2026-01-03'},
          {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',size:1,date:'2026-01-02'},
          {stem:'a3',chat:'F',thumb:'thumb/F/a3.jpg',file:'f',size:1,date:'2026-01-01'}]]};
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(dedup)))});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 // wait for BOOT's manifest fetch to resolve (bootDone=true) before opening
 // the Duplicates view, same as a real user would after the page finishes loading
 setTimeout(()=>{
   click(doc.getElementById('dedupBtn'));
   setTimeout(()=>{
     var cards=doc.querySelectorAll('.dupcard');
     var stems=Array.from(cards).map(function(c){return c.dataset.stem;});
     console.log('cards rendered:',cards.length,'stems:',JSON.stringify(stems));
     var ok = cards.length===2 && stems.indexOf('a2')<0 && stems.indexOf('a1')>=0 && stems.indexOf('a3')>=0;
     console.log(ok?'PASS: already-deleted a2 hidden, live a1/a3 pair still shown':'FAIL');
     var bar=doc.getElementById('dupBar');
     console.log('bar text mentions hidden ghost:', bar && /already-deleted/.test(bar.textContent) ? 'PASS' : 'FAIL (no ghost-hidden indicator)');
   },200);
 },100);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);
