const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// manifest-hidden-flag filtering (no toggle). The manifest is the source of
// truth: build_manifest.py stamps non-newest members of duplicate groups with
// "hidden":true. Browsing must behave like a desktop folder that simply
// doesn't contain the duplicate -- hidden items are filtered from every
// normal view, but a folder whose items are ALL hidden still appears (with 0
// visible items), and the Duplicates review page still shows every member.
const manifest=[
  {stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',type:'image',date:'2026-01-03',size:100},
  {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',type:'image',date:'2026-01-02',size:100,hidden:true},
  {stem:'a3',chat:'F',thumb:'thumb/F/a3.jpg',file:'f',type:'image',date:'2026-01-01',size:100},
  {stem:'g1',chat:'G',thumb:'thumb/G/g1.jpg',file:'f',type:'image',date:'2026-01-01',size:100,hidden:true}
];
const dedup={generated:'2026-06-04',hamming:6,scanned:4,dup_groups:1,dup_items:2,
 groups:[[{stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',size:100,date:'2026-01-03'},
          {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',size:100,date:'2026-01-02'}]]};
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F','G'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(dedup)))});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
function folderTile(name){
  var f=null; doc.querySelectorAll('#folderGrid .folder').forEach(function(x){ if(x.dataset.chat===name) f=x; });
  return f;
}
setTimeout(()=>{ try{
 setTimeout(()=>{
   var sub=doc.getElementById('sub').textContent;
   console.log('landing subtitle:',JSON.stringify(sub));
   console.log(sub==='2 folders · 2 items total'?'PASS subtitle visibleCount':'FAIL subtitle (got '+sub+')');
   var F=folderTile('F'), G=folderTile('G');
   console.log('folder F present:',!!F,'folder G present:',!!G);
   if(!F||!G) console.log('FAIL missing folder tile');
   else{
     var fc=F.querySelector('.fcount'), gc=G.querySelector('.fcount');
     console.log('F count:',fc&&fc.textContent,'expect 2 items');
     console.log('G count:',gc&&gc.textContent,'expect 0 items');
     console.log((fc&&fc.textContent==='2 items')?'PASS F shows 2 visible':'FAIL F count');
     console.log((gc&&gc.textContent==='0 items')?'PASS G remains with 0 items':'FAIL G count');
   }
   if(F){ click(F); }
   setTimeout(()=>{
     var tiles=doc.querySelectorAll('#photoGrid .tile');
     var stems=Array.from(tiles).map(function(t){return t.dataset.stem;});
     console.log('F folder tiles:',stems.length,'stems:',JSON.stringify(stems));
     var ok2=stems.length===2&&stems.indexOf('a1')>=0&&stems.indexOf('a3')>=0&&stems.indexOf('a2')<0;
     console.log(ok2?'PASS F shows exactly a1+a3 (a2 hidden)':'FAIL F tile set');
     // back to landing, then open the Duplicates review page
     click(doc.getElementById('backBtn'));
     setTimeout(()=>{
       click(doc.getElementById('dedupBtn'));
       setTimeout(()=>{
         var cards=doc.querySelectorAll('#dupView .dupcard');
         var stems2=Array.from(cards).map(function(c){return c.dataset.stem;});
         console.log('review cards:',stems2.length,'stems:',JSON.stringify(stems2));
         var a2=null; cards.forEach(function(c){ if(c.dataset.stem==='a2') a2=c; });
         console.log('review shows a1+a2:',(stems2.length===2&&stems2.indexOf('a1')>=0&&stems2.indexOf('a2')>=0)?'PASS':'FAIL');
         console.log('a2 card has class dchidden:',(a2&&a2.classList.contains('dchidden'))?'PASS':'FAIL');
         process.exit(0);
       },200);
     },100);
   },200);
 },100);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);process.exit(1);} },800);
