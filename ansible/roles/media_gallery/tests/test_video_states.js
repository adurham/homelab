const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: video in the lightbox is a state machine, not a bare <video>.
// Guards: the autoplay-next toggle exists and persists, and the status line
// reports buffering / seek / codec failure / poster-pending instead of leaving
// a black rectangle with no explanation.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const manifest=[
  {stem:'v1',chat:'m',thumb:'t/v1.jpg',file:'by-chat/m/v1.mp4',type:'video',date:'2026-01-02',size:10},
  {stem:'v2',chat:'m',thumb:'t/v2.jpg',file:'by-chat/m/v2.mp4',type:'video',date:'2026-01-01',size:10}
];
let fails=0;const results=[];
function T(n,c,d){ results.push((c?'PASS':'FAIL')+'  '+n+(d?('   ['+d+']'):'')); if(!c)fails++; }
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',url:'https://gallery.test/',beforeParse(w){
  w.fetch=(u)=>{u=String(u);
    if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
    if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['m'])});
    if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
    return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
  w.alert=()=>{};w.confirm=()=>true;w.prompt=()=>'';w.scrollTo=()=>{};
}});
const w=dom.window, doc=w.document;
function wait(fn,cb,t){t=t===undefined?60:t; if(fn()||t<=0)return cb(); setTimeout(()=>wait(fn,cb,t-1),100);}
wait(()=>doc.querySelectorAll('#folderGrid .folder').length>0, ()=>{
  doc.querySelector('#folderGrid .folder').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  wait(()=>doc.querySelectorAll('#photoGrid .tile').length===2, ()=>{
    doc.querySelectorAll('#photoGrid .tile')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
    setTimeout(()=>{
      const auto=doc.getElementById('lbAuto');
      T('autoplay toggle exists in the lightbox', !!auto, auto?auto.textContent:'(none)');
      T('autoplay defaults to Off', /Off/.test(auto.textContent), auto.textContent);
      auto.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
      T('autoplay flips to On', /On/.test(auto.textContent), auto.textContent);
      T('autoplay choice persists', w.localStorage.getItem('gal.autoplay.v1')==='1', w.localStorage.getItem('gal.autoplay.v1'));
      const vid=doc.querySelector('#lbMedia video');
      T('video uses preload=metadata', !!vid && vid.getAttribute('preload')==='metadata', vid?vid.getAttribute('preload'):'no video');
      const st=doc.getElementById('lbStatus');
      T('status line exists', !!st);
      vid.dispatchEvent(new w.Event('waiting'));
      T('buffering is reported', /Buffering/.test(st.textContent), st.textContent);
      vid.dispatchEvent(new w.Event('playing'));
      T('playing clears the status', st.textContent==='', JSON.stringify(st.textContent));
      vid.dispatchEvent(new w.Event('error'));
      T('codec failure is explained', /codec/.test(st.textContent), st.textContent);
      console.log(results.join('\n'));
      console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
      process.exit(fails===0?0:1);
    },400);
  });
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},25000);
