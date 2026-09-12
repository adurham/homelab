const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// Regression test for the 2026-09-12 fix: user reported the gallery "sorts
// largest files to lowest" even though the coded default is "Newest first"
// (<option value="new"> is listed first and nothing in the JS ever set a
// different default). Root cause: browsers persist a <select>'s
// last-CHOSEN value across page reloads as part of native form-state
// restoration (independent of autofill) -- picking "Largest first" once
// (e.g. while hunting for space-hogging files) silently became the
// permanent apparent default on every future visit, with the actual coded
// default never having changed. Fixed two ways: (1) autocomplete="off" on
// the <select> tells browsers not to restore its value at all, (2) BOOT
// explicitly sets elSort.value='new' as belt-and-suspenders in case any
// browser/version restores the value before scripts finish running.
const manifest=[
 {stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',type:'image',date:'2026-01-01',size:100},
 {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',type:'image',date:'2026-01-02',size:50000},
];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F'])});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
const sortEl = doc.getElementById('sort');
setTimeout(()=>{
  var okValue = sortEl.value==='new';
  console.log('sort dropdown value after boot:', sortEl.value, okValue?'PASS (reset to newest-first)':'FAIL (not newest-first)');
  var okAttr = sortEl.getAttribute('autocomplete')==='off';
  console.log('autocomplete attr:', sortEl.getAttribute('autocomplete'), okAttr?'PASS':'FAIL');
},800);
