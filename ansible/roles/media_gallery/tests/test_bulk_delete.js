const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'person_1',file:'f',thumb:'thumb/person_1/a1.jpg',type:'image',date:'2026-01-01'},
 {stem:'a2',chat:'person_1',file:'f',thumb:'thumb/person_1/a2.jpg',type:'image',date:'2026-01-02'},
];
// NOTE 2026-09-12: bulkDelete's real click handler batches into ONE
// /trashmark POST (chat + stems[]), not N individual /trash/<chat>/<stem>
// calls -- that was an older per-item API shape the code has since moved
// past (see gallery_index.html's bulkDelete handler / trash_service.py's
// /trashmark). This test previously watched for /trash/ hits and always
// saw zero, silently failing every run regardless of whether bulk delete
// actually worked. Fixed to assert against the real, current endpoint.
let trashmarkCalls=[];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('/trashmark')>=0){trashmarkCalls.push(JSON.parse(opts.body));return Promise.resolve({status:200,json:()=>Promise.resolve({marked:2})});}
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
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
 setTimeout(()=>{
   console.log('trashmark calls:',JSON.stringify(trashmarkCalls));
   var ok=trashmarkCalls.length===1&&trashmarkCalls[0].chat==='person_1'&&trashmarkCalls[0].stems.length===2;
   console.log(ok?'>>> DELETE PASS <<<':'>>> DELETE FAIL <<<');
 },200);
},800);
