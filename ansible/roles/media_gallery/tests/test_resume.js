const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: resume + recent folders.
// A folder is a container (a "model"), and with 516 of them plus folders of
// 15,865 items, reopening the app used to mean remembering folder, sort and
// position. This guards the bookmark layer: opening a photo records a
// stem-anchored bookmark, the landing page shows a Continue card for it, and
// clicking that card re-opens the folder.
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
function mkdom(){
  return new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/',beforeParse(window){
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
function waitUntil(fn,cb,tries){ tries=tries===undefined?60:tries; if(fn()||tries<=0) return cb(); setTimeout(()=>waitUntil(fn,cb,tries-1),100); }
const folders=doc=>Array.from(doc.querySelectorAll('#folderGrid .folder'));
const tiles=doc=>Array.from(doc.querySelectorAll('#photoGrid .tile'));

const d1=mkdom(); const w1=d1.window, doc1=w1.document;
waitUntil(()=>folders(doc1).length>0, ()=>{
  T('landing starts with no Continue card', doc1.getElementById('resumeBar').className!=='show', doc1.getElementById('resumeBar').className);
  click(w1, folders(doc1).find(f=>f.dataset.chat==='person_7'));
  waitUntil(()=>tiles(doc1).length===2, ()=>{
    T('folder opened', tiles(doc1).length===2, tiles(doc1).map(t=>t.dataset.stem).join(','));
    click(w1, tiles(doc1)[1]);                        // open the 2nd photo in the lightbox
    setTimeout(()=>{
      let st=null; try{ st=JSON.parse(w1.localStorage.getItem('gal.resume.v1')||'null'); }catch(_){}
      T('opening a photo records a bookmark', !!(st&&st.by&&st.by.person_7), st?JSON.stringify(st.by&&st.by.person_7):'null');
      T('bookmark is stem-anchored, not index-anchored', !!(st&&st.by.person_7&&st.by.person_7.stem==='g2'), st&&st.by.person_7&&st.by.person_7.stem);
      T('folder lands in the recent list', !!(st&&st.recent&&st.recent[0]==='person_7'), st&&st.recent&&st.recent.join(','));
      click(w1, doc1.getElementById('lb'));            // close the lightbox
      click(w1, doc1.getElementById('backBtn'));       // back to the folders page
      setTimeout(()=>{
        const bar=doc1.getElementById('resumeBar');
        T('landing shows the Continue card', bar.className==='show', bar.className);
        const t=(bar.querySelector('.rcontinue')||{}).textContent||'';
        T('Continue names the folder and the item', /Continue: person_7/.test(t) && /item 2 of 2/.test(t), t.trim());
        const btn=bar.querySelector('.rcontinue');
        click(w1, btn);
        setTimeout(()=>{
          T('Continue re-opens the folder', tiles(doc1).length===2 && w1.location.hash.indexOf('#f=person_7')===0,
            tiles(doc1).length+' tiles hash='+w1.location.hash);
          console.log(results.join('\n'));
          console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
          process.exit(fails===0?0:1);
        },500);
      },400);
    },300);
  });
});
setTimeout(()=>{ console.log('TIMEOUT'); console.log(results.join('\n')); process.exit(2); },30000);
