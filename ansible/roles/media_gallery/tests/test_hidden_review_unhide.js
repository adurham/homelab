const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// Unhide/re-hide via POST /sethidden. Hidden items are filtered from browsing,
// but the Duplicates review page shows every member (with a dchidden marker).
// "Keep all" unhides non-newest members /sethidden {stems:[...],hidden:false};
// the per-card toggle flips keep<->trash and drives the same endpoint (keep-
// >unhide, trash->re-hide). A 200 response applies the change in place.
const manifest=[
  {stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',type:'image',date:'2026-01-03',size:100},
  {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',type:'image',date:'2026-01-02',size:100,hidden:true}
];
const dedup={generated:'2026-06-04',hamming:6,scanned:2,dup_groups:1,dup_items:2,
 groups:[[{stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',size:100,date:'2026-01-03'},
          {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',size:100,date:'2026-01-02'}]]};
const sethiddenCalls=[];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(dedup)))});
   if(u.indexOf('/sethidden')>=0){ const body=JSON.parse(opts.body); sethiddenCalls.push(body); return Promise.resolve({status:200,json:()=>Promise.resolve({})}); }
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
function enterFolder(name){
  var f=null; doc.querySelectorAll('#folderGrid .folder').forEach(function(x){ if(x.dataset.chat===name) f=x; });
  if(f) click(f);
}
setTimeout(()=>{ try{
 setTimeout(()=>{
   // --- open Duplicates review page ---
   click(doc.getElementById('dedupBtn'));
   setTimeout(()=>{
     var cards=doc.querySelectorAll('#dupView .dupcard');
     var a2=null; cards.forEach(function(c){ if(c.dataset.stem==='a2') a2=c; });
     console.log('=== review shows 2 cards ===');
     console.log(cards.length===2?'PASS':'FAIL (got '+cards.length+')');
     console.log('a2 dchidden initially:',(a2&&a2.classList.contains('dchidden'))?'PASS':'FAIL');
     // --- "Keep all": unhide the non-newest members ---
     click(doc.querySelector('.dg-mark[data-act="keepall"]'));
     setTimeout(()=>{
       console.log('=== after Keep all ===');
       var body=sethiddenCalls[0];
       console.log('sethidden call:',JSON.stringify(body));
       var okBody=body&&body.stems.length===1&&body.stems.indexOf('a2')>=0&&body.hidden===false;
       console.log(okBody?'PASS /sethidden {stems:[a2],hidden:false}':'FAIL sethidden body');
       console.log('a2 no longer dchidden:',(a2&&!a2.classList.contains('dchidden'))?'PASS':'FAIL');
       // --- navigate back into folder F: a2 should now be visible ---
       click(doc.getElementById('backBtn'));
       setTimeout(()=>{
         enterFolder('F');
         setTimeout(()=>{
           var tiles=doc.querySelectorAll('#photoGrid .tile');
           var stems=Array.from(tiles).map(function(t){return t.dataset.stem;});
           console.log('=== after unhide, F folder ===');
           console.log('tiles:',stems.length,'stems:',JSON.stringify(stems));
           console.log((stems.length===2&&stems.indexOf('a2')>=0)?'PASS a2 now visible':'FAIL (got '+JSON.stringify(stems)+')');
           // --- per-card toggle: a2 default act is trash; click once -> keep (unhide),
           //     click again -> trash (re-hide). Assert the second /sethidden has hidden:true.
           click(doc.getElementById('dedupBtn'));
           setTimeout(()=>{
             var cards2=doc.querySelectorAll('#dupView .dupcard');
             var a2b=null; cards2.forEach(function(c){ if(c.dataset.stem==='a2') a2b=c; });
             console.log('=== after re-opening review (post-unhide) ===');
             console.log('a2 dchidden after unhide(should be false):',(a2b&&!a2b.classList.contains('dchidden'))?'PASS':'FAIL');
             var tg=a2b.querySelector('.dc-toggle');
             click(tg);                 // trash -> keep  => /sethidden hidden:false
             click(tg);                 // keep  -> trash => /sethidden hidden:true
             setTimeout(()=>{
               var last=sethiddenCalls[sethiddenCalls.length-1];
               console.log('last sethidden call:',JSON.stringify(last));
               var okToggle=last&&last.stems.length===1&&last.stems.indexOf('a2')>=0&&last.hidden===true;
               console.log(okToggle?'PASS per-card toggle re-hides a2':'FAIL per-card toggle');
               setTimeout(()=>{ process.exit(0); },100);
             },150);
           },200);
         },150);
       },150);
     },150);
   },200);
 },100);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);process.exit(1);} },800);
