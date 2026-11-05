const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: date entry points — the in-folder year rail and the landing-page
// "On this day" strip. A 253K-item chronological library needs somewhere to
// start other than scrolling.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const now=new Date();
const mm=('0'+(now.getMonth()+1)).slice(-2), dd=('0'+(now.getDate())).slice(-2);
const manifest=[
  // this folder has two clear years
  {stem:'a19',chat:'model_a',thumb:'t/a19.jpg',file:'by-chat/model_a/a19.jpg',type:'image',date:'2019-05-02T00:00:00',size:1},
  {stem:'b21',chat:'model_a',thumb:'t/b21.jpg',file:'by-chat/model_a/b21.jpg',type:'image',date:'2021-07-09T00:00:00',size:1},
  {stem:'c21',chat:'model_a',thumb:'t/c21.jpg',file:'by-chat/model_a/c21.jpg',type:'image',date:'2021-08-10T00:00:00',size:1},
  // three files sharing today's month/day, across two folders
  {stem:'o25',chat:'model_a',thumb:'t/o25.jpg',file:'by-chat/model_a/o25.jpg',type:'image',date:'2025-'+mm+'-'+dd+'T10:00:00',size:1},
  {stem:'o23',chat:'model_b',thumb:'t/o23.jpg',file:'by-chat/model_b/o23.jpg',type:'image',date:'2023-'+mm+'-'+dd+'T11:00:00',size:1},
  {stem:'o20',chat:'model_b',thumb:'t/o20.jpg',file:'by-chat/model_b/o20.jpg',type:'image',date:'2020-'+mm+'-'+dd+'T12:00:00',size:1}
];
let fails=0;const results=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/',beforeParse(w){
  w.fetch=(u)=>{u=String(u);
    if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
    if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['model_a','model_b'])});
    if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
    return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
  w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
}});
const w=dom.window, doc=w.document;
function wait(fn,cb,t){t=t===undefined?60:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}
wait(()=>doc.querySelectorAll('#folderGrid .folder').length>0, ()=>{
  const otd=doc.getElementById('otdBar');
  T('On this day strip renders on the landing page', otd.style.display==='block', otd.style.display);
  const tiles=otd.querySelectorAll('.otd-tile');
  T('it shows at least the three same-day files', tiles.length>=3, tiles.length+' tiles');
  T('each tile is labelled with its year', /20\d\d/.test((otd.querySelector('.otd-yr')||{}).textContent||''), (otd.querySelector('.otd-yr')||{}).textContent);
  T('caption counts years', /from \d year/.test((otd.querySelector('.otd-head')||{}).textContent||''), (otd.querySelector('.otd-head')||{}).textContent);
  // open the two-year folder and check the rail
  doc.querySelector('#folderGrid .folder[data-chat="model_a"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  wait(()=>doc.querySelectorAll('#photoGrid .tile').length>0, ()=>{
    const rail=doc.getElementById('dateRail');
    T('year rail appears inside a multi-year folder', rail.style.display==='flex', rail.style.display);
    const yrs=Array.from(rail.querySelectorAll('.yr')).map(b=>b.textContent);
    T('rail lists every year present', yrs.length>=3 && /2019/.test(yrs.join(' ')) && /2021/.test(yrs.join(' ')), yrs.join(' '));
    const b19=Array.from(rail.querySelectorAll('.yr')).find(b=>/2019/.test(b.textContent));
    b19.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
    T('clicking a year does not throw', true);
    console.log(results.join('\n'));
    console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
    process.exit(fails===0?0:1);
  });
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},25000);
