const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-09-30: guards the two reported UX regressions plus the new route layer:
//   1. Typing in the search box while on the LANDING page did nothing at all
//      (search only filtered an already-open folder).
//   2. Refreshing while inside a folder dumped you back to the landing page
//      (BOOT unconditionally rendered folders; no view state was persisted).
// Also covers: in-folder search still works, clearing restores the folder,
// Escape exits the results view, a stale folder name in the URL falls back to
// the landing page instead of an empty grid, and the #dup route works.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const manifest=[
  {stem:'g1',chat:'person_7',thumb:'thumb/person_7/g1.jpg',file:'by-chat/person_7/g1.jpg',type:'image',date:'2026-01-03',size:100},
  {stem:'g2',chat:'person_7',thumb:'thumb/person_7/g2.jpg',file:'by-chat/person_7/g2.jpg',type:'image',date:'2026-01-02',size:100},
  {stem:'l1',chat:'person_11',thumb:'thumb/person_11/l1.jpg',file:'by-chat/person_11/l1.mp4',type:'video',date:'2026-01-04',size:200},
  {stem:'l2',chat:'person_11',thumb:'thumb/person_11/l2.jpg',file:'by-chat/person_11/l2.jpg',type:'image',date:'2026-01-01',size:100}
];
let fails=0;const results=[];
function T(name,cond,detail){ results.push((cond?'PASS':'FAIL')+'  '+name+(detail?('   ['+detail+']'):'')); if(!cond)fails++; }
function mkdom(hash){
  return new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/'+(hash||''),beforeParse(window){
   window.fetch=(url)=>{const u=String(url);
     if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
     if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['person_7','person_11'])});
     if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
     if(u.indexOf('trashqueue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(null)});
     if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({generated:'x',groups:[]})});
     return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
   window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
  }});
}
function click(w,el){el.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));}
function typeSearch(w,doc,q){const sb=doc.getElementById('searchBox');sb.value=q;sb.dispatchEvent(new w.Event('input',{bubbles:true}));}
function stems(doc){return Array.from(doc.querySelectorAll('#photoGrid .tile')).map(t=>t.dataset.stem);}
function waitUntil(fn,cb,tries){ tries=tries===undefined?50:tries;
  if(fn()||tries<=0) return cb();
  setTimeout(()=>waitUntil(fn,cb,tries-1),100);
}

// Scenario 1: open folder, search inside, hash written
const d1=mkdom(); const w1=d1.window; const doc1=w1.document;
waitUntil(()=>doc1.querySelectorAll('#folderGrid .folder').length>0, ()=>{
  const person7=Array.from(doc1.querySelectorAll('#folderGrid .folder')).find(f=>f.dataset.chat==='person_7');
  if(!person7){ T('setup: person_7 tile rendered',false); return done(); }
  click(w1,person7);
  waitUntil(()=>stems(doc1).length===2, ()=>{
    T('open folder shows its items', stems(doc1).length===2, stems(doc1).join(','));
    T('route hash = #f=person_7', w1.location.hash==='#f=person_7', w1.location.hash);
    typeSearch(w1,doc1,'g1');
    setTimeout(()=>{
      T('in-folder search filters', stems(doc1).length===1 && stems(doc1)[0]==='g1', stems(doc1).join(','));
      typeSearch(w1,doc1,'');
      setTimeout(()=>{
        T('clearing search restores folder', stems(doc1).length===2, stems(doc1).join(','));
        scenario2();
      },400);
    },400);
  });
});

// Scenario 2: refresh inside a folder restores the folder
function scenario2(){
  const d2=mkdom('#f=person_7'); const w2=d2.window; const doc2=w2.document;
  waitUntil(()=>stems(doc2).length===2, ()=>{
    T('refresh inside folder restores folder view', stems(doc2).join(',')==='g1,g2',
      stems(doc2).join(',')+' hash='+w2.location.hash);
    scenario3();
  });
}

// Scenario 3: search from the landing page (the reported bug)
function scenario3(){
  const d3=mkdom(); const w3=d3.window; const doc3=w3.document;
  waitUntil(()=>doc3.querySelectorAll('#folderGrid .folder').length>0, ()=>{
    typeSearch(w3,doc3,'person_11');
    setTimeout(()=>{
      const s=stems(doc3);
      T('landing search enters global results', s.length===2 && s.indexOf('l1')>=0 && s.indexOf('l2')>=0, s.join(','));
      T('landing search route = #s=person_11', w3.location.hash.indexOf('#s=person_11')===0, w3.location.hash);
      T('landing grid hidden during search', doc3.getElementById('folderGrid').style.display==='none');
      scenario4();
    },500);
  });
}

// Scenario 4: refresh while searching restores the results
function scenario4(){
  const d4=mkdom('#s=person_11'); const w4=d4.window; const doc4=w4.document;
  waitUntil(()=>stems(doc4).length===2, ()=>{
    const s=stems(doc4);
    T('refresh in search restores results', s.length===2 && w4.location.hash.indexOf('#s=person_11')===0, s.join(','));
    doc4.getElementById('searchBox').dispatchEvent(new w4.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    setTimeout(()=>{
      T('Escape exits search to landing', doc4.getElementById('folderGrid').style.display==='grid', 'hash='+w4.location.hash);
      scenario5();
    },400);
  });
}

// Scenario 5: ghost folder -> landing; dup route opens duplicates
function scenario5(){
  const d5=mkdom('#f=Ghost'); const doc5=d5.window.document;
  waitUntil(()=>doc5.querySelectorAll('#folderGrid .folder').length>0, ()=>{
    T('ghost folder falls back to landing', doc5.getElementById('folderGrid').style.display==='grid');
    const d6=mkdom('#dup'); const doc6=d6.window.document;
    setTimeout(()=>{
      T('dup route opens duplicates view', doc6.getElementById('dupView').style.display==='block');
      done();
    },1200);
  });
}

function done(){
  console.log(results.join('\n'));
  console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
  process.exit(fails===0?0:1);
}
setTimeout(()=>{ console.log('TIMEOUT — scenarios did not complete'); console.log(results.join('\n')); process.exit(2); }, 60000);
