const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: in-folder filters (type / year / size / unseen).
// Before this, the only way to narrow a folder was matching text in the stem.
// A model folder is a container, not a curated set: "videos from 2021" and
// "what haven't I opened" are the two questions the owner actually asks.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const MB=1024*1024;
const manifest=[
  {stem:'i19s',chat:'model_a',thumb:'t/i19s.jpg',file:'by-chat/model_a/i19s.jpg',type:'image',date:'2019-05-01T00:00:00',size:2*MB},
  {stem:'i21b',chat:'model_a',thumb:'t/i21b.jpg',file:'by-chat/model_a/i21b.jpg',type:'image',date:'2021-07-01T00:00:00',size:200*MB},
  {stem:'v21b',chat:'model_a',thumb:'t/v21b.jpg',file:'by-chat/model_a/v21b.mp4',type:'video',date:'2021-08-01T00:00:00',size:150*MB},
  {stem:'i21s',chat:'model_a',thumb:'t/i21s.jpg',file:'by-chat/model_a/i21s.jpg',type:'image',date:'2021-09-01T00:00:00',size:3*MB}
];
let fails=0;const results=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/',beforeParse(w){
  w.fetch=(u)=>{u=String(u);
    if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
    if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['model_a'])});
    if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
    return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
  w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
}});
const w=dom.window, doc=w.document;
const stems=()=>Array.from(doc.querySelectorAll('#photoGrid .tile')).map(t=>t.dataset.stem);
const bar=()=>doc.getElementById('filterBar');
const sels=()=>Array.from(bar().querySelectorAll('select'));
function pick(i,val){ const s=sels()[i]; s.value=val; s.dispatchEvent(new w.Event('change',{bubbles:true})); }
function wait(fn,cb,t){t=t===undefined?60:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}

wait(()=>doc.querySelectorAll('#folderGrid .folder').length>0, ()=>{
  doc.querySelector('#folderGrid .folder').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  wait(()=>stems().length===4, ()=>{
    T('folder opens with all items', stems().length===4, stems().join(','));
    T('filter bar is visible in a folder', bar().style.display==='flex', bar().style.display);
    T('three selects: type, year, size', sels().length===3, sels().length+' selects');
    pick(0,'video');
    setTimeout(()=>{
      T('type=video keeps only videos', stems().join(',')==='v21b', stems().join(','));
      pick(0,'');
      pick(1,'2019');
      setTimeout(()=>{
        T('year=2019 keeps only that year', stems().join(',')==='i19s', stems().join(','));
        pick(1,'');
        pick(2,'l');
        setTimeout(()=>{
          T('size >100MB keeps the big items', stems().sort().join(',')==='i21b,v21b', stems().join(','));
          pick(2,'');
          // unseen: open i21s in the lightbox (marks it seen), then filter
          const t=Array.from(doc.querySelectorAll('#photoGrid .tile')).find(x=>x.dataset.stem==='i21s');
          t.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
          setTimeout(()=>{
            const lb=doc.getElementById('lb'); if(lb) lb.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
            const un=Array.from(bar().querySelectorAll('button')).find(b=>/Unseen/.test(b.textContent));
            un.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
            setTimeout(()=>{
              T('unseen filter drops the photo I just opened', stems().indexOf('i21s')<0 && stems().length===3, stems().join(','));
              const cl=Array.from(bar().querySelectorAll('button')).find(b=>/Clear filters/.test(b.textContent));
              T('clear button appears while filtering', !!cl);
              cl.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
              setTimeout(()=>{
                T('clear restores every item', stems().length===4, stems().join(','));
                console.log(results.join('\n'));
                console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
                process.exit(fails===0?0:1);
              },300);
            },300);
          },300);
        },300);
      },300);
    },300);
  });
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},30000);
