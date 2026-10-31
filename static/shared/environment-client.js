/* Bind each open page to its initial environment revision. Old tabs cannot save into a newly selected database. */
(function(){
 if(window.__aiopsEnvironmentClient)return;window.__aiopsEnvironmentClient=true;
 const original=window.fetch.bind(window),root=new URL('api/',document.baseURI);
 let initial;
 function profile(){return initial||=(original(new URL('environment',root),{cache:'no-store'}).then(r=>r.json()).then(b=>{if(b.code!==0)throw Error(b.message||'无法读取数据环境');return b.data;})).catch(e=>{initial=null;throw e;});}
 window.fetch=async function(input,options){
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,document.baseURI);
  if(url.origin===root.origin&&url.pathname.startsWith(root.pathname)&&!url.pathname.startsWith(root.pathname+'environment')){
   const p=await profile();const headers=new Headers(options?.headers||(input instanceof Request?input.headers:undefined));headers.set('x-aiops-environment-revision',String(p.revision||0));
   return original(input,{...options,headers});
  }
  return original(input,options);
 };
})();
