const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// 2026-09-12: manifest now includes BOTH stems. Previously this test's
// manifest only listed 'a1' (not 'a2') and still expected 2 cards to render
// -- that assertion was actually exercising the BUG this session fixed:
// renderDuplicates() now live-filters dup groups against the manifest, so a
// stem missing from the manifest is (correctly) treated as already-deleted
// and dropped. Making the manifest complete here keeps this test's original
// intent intact -- "every member of a still-fully-live group renders" --
// without asserting the old bug. See test_dedup_live_filter.js for the new
// "already-deleted members get hidden" behavior this replaces.
const manifest=[
  {stem:'a1',chat:'person1',thumb:'thumb/person1/a1.jpg',file:'f',type:'image',date:'2026-01-02',size:16000},
  {stem:'a2',chat:'person1',thumb:'thumb/person1/a2.jpg',file:'f',type:'image',date:'2026-01-01',size:15000}
];
const dedup={generated:'2026-06-04',hamming:6,scanned:875,dup_groups:1,dup_items:2,
 groups:[[{stem:'a1',chat:'person1',thumb:'thumb/person1/a1.jpg',file:'f',size:16000,date:'2026-01-02'},
          {stem:'a2',chat:'person1',thumb:'thumb/person1/a2.jpg',file:'f',size:15000,date:'2026-01-01'}]]};
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['person1'])});
   if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(dedup)))});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 click(doc.getElementById('dedupBtn'));
 setTimeout(()=>{
   var cards=doc.querySelectorAll('.dupcard');
   console.log('cards rendered for a 2-member group (both live):',cards.length,'(expect 2)', cards.length===2?'PASS':'FAIL');
   cards.forEach((c,i)=>console.log('  card',i,'stem=',c.dataset.stem,'class=',c.className));
 },200);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);
