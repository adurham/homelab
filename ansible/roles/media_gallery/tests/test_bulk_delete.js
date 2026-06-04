const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'person_1',file:'f',thumb:'thumb/person_1/a1.jpg',type:'image',date:'2026-01-01'},
 {stem:'a2',chat:'person_1',file:'f',thumb:'thumb/person_1/a2.jpg',type:'image',date:'2026-01-02'},
];
const dels=[];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});if(u.indexOf('/trash/')>=0)dels.push(u);return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=(m)=>{window.__a=m;};window.confirm=()=>true;window.prompt=()=>'NF';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{
 let p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person_1')p1=f;});
 click(p1);
 let tiles=doc.querySelectorAll('#photoGrid .tile');
 click(tiles[0].querySelector('.selbox')); click(tiles[1].querySelector('.selbox'));
 click(doc.getElementById('bulkDelete'));
 setTimeout(()=>{console.log('delete calls:',dels.length,'(expect 2)'); console.log(dels.length===2?'>>> DELETE PASS <<<':'>>> DELETE FAIL <<<');},200);
},800);
