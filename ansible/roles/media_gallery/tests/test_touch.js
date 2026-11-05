const fs=require('fs');const {JSDOM}=require('jsdom');
// 2026-11-05: touch affordances. The gallery is used from a phone over the
// tailnet, where hover shows nothing and 26-28 px controls are a miss-fest.
// Guards the coarse-pointer rules and the lightbox swipe.
const HTML_PATH=require('path').resolve(__dirname,'../files/gallery_index.html');
const html=fs.readFileSync(HTML_PATH,'utf8');
const manifest=[
  {stem:'a',chat:'m',thumb:'t/a.jpg',file:'by-chat/m/a.jpg',type:'image',date:'2026-01-02',size:1},
  {stem:'b',chat:'m',thumb:'t/b.jpg',file:'by-chat/m/b.jpg',type:'image',date:'2026-01-01',size:1}
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
T('coarse-pointer rules are present', /@media \(pointer:coarse\)/.test(html));
T('touch targets are >=44px', /\.tile \.selbox,\.tile \.trash\{width:44px/.test(html));
T('search box avoids iOS zoom', /#searchBox\{font-size:16px/.test(html));
wait(()=>doc.querySelectorAll('#folderGrid .folder').length>0, ()=>{
  doc.querySelector('#folderGrid .folder').dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
  wait(()=>doc.querySelectorAll('#photoGrid .tile').length===2, ()=>{
    doc.querySelectorAll('#photoGrid .tile')[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));
    setTimeout(()=>{
      const lb=doc.getElementById('lb');
      const first=doc.querySelector('#lbMedia img').getAttribute('src');
      function pev(type,x,y,pt){
        const e=new w.Event(type,{bubbles:true});
        Object.defineProperty(e,'clientX',{value:x}); Object.defineProperty(e,'clientY',{value:y});
        Object.defineProperty(e,'pointerType',{value:pt||'touch'});
        lb.dispatchEvent(e);
      }
      pev('pointerdown',300,400); pev('pointerup',110,404);
      setTimeout(()=>{
        const second=doc.querySelector('#lbMedia img').getAttribute('src');
        T('swipe left advances to the next item', first!==second, first+' -> '+second);
        pev('pointerdown',120,400); pev('pointerup',320,402);
        setTimeout(()=>{
          const third=doc.querySelector('#lbMedia img').getAttribute('src');
          T('swipe right goes back', third===first, third);
          pev('pointerdown',300,400); pev('pointerup',290,404);
          setTimeout(()=>{
            const after=doc.querySelector('#lbMedia img').getAttribute('src');
            T('a short drag does not navigate', after===first, after);
            console.log(results.join('\n'));
            console.log(fails===0?'ALL PASS':(fails+' FAILURES'));
            process.exit(fails===0?0:1);
          },250);
        },250);
      },250);
    },400);
  });
});
setTimeout(()=>{console.log('TIMEOUT');console.log(results.join('\n'));process.exit(2);},25000);
