if(window.location.protocol==="file:")window.location.replace("http://127.0.0.1:8000/documents/new");
  const $=id=>document.getElementById(id);
  async function csrf(){let token=document.cookie.split("; ").find(item=>item.startsWith("scope_csrf="))?.split("=").slice(1).join("=");if(!token){const response=await fetch("/api/security/csrf",{credentials:"same-origin"});token=(await response.json()).csrf_token}return decodeURIComponent(token||"")}
  async function api(url,options={}){const method=(options.method||"GET").toUpperCase();const isForm=options.body instanceof FormData;const headers=isForm?{...(options.headers||{})}:{"Content-Type":"application/json",...(options.headers||{})};if(!["GET","HEAD","OPTIONS"].includes(method))headers["X-CSRF-Token"]=await csrf();let response;try{response=await fetch(url,{...options,headers})}catch(error){throw new Error("Cannot reach the Scope Sentinel API.")}const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(window.formatApiError(body, response.status));return body}
  function updateType(){const amendment=$("documentType").value==="AMENDMENT";$("parentGroup").classList.toggle("hidden",!amendment);$("supersedesGroup").classList.toggle("hidden",!amendment);$("uploadGroup").classList.toggle("hidden",amendment);$("version").value=amendment?"1.1":"1.0";$("notice").textContent=amendment?"Select the parent SOW and describe only the changed clauses.":"Create a standalone SOW using an uploaded file or pasted text."}
  async function loadParents(){
    try{
      const rows=await api("/api/contracts");
      const parents=rows.filter(row=>row.document_type==="SOW"&&row.status==="ACTIVE");
      for(const row of parents){
        const option=document.createElement("option");
        option.value=row.id;
        option.textContent=row.title+" · v"+row.version+" (#"+row.id+")";
        $("parentContract").append(option);
      }
    }catch(error){$("notice").textContent=error.message;}
  }
  $("documentType").addEventListener("change",updateType);
  $("save").addEventListener("click",async()=>{const button=$("save");button.disabled=true;try{let result;if($("documentType").value==="AMENDMENT"){if(!$("parentContract").value)throw new Error("Select a parent SOW.");result=await api(`/api/contracts/${$("parentContract").value}/amendments/text`,{method:"POST",body:JSON.stringify({title:$("title").value,content:$("content").value,version:$("version").value,effective_date:$("effectiveDate").value||new Date().toISOString().slice(0,10),supersedes_clause_refs:$("supersedes").value.split(",").map(value=>value.trim()).filter(Boolean)})})}else if($("file").files[0]){const form=new FormData();form.append("file",$("file").files[0]);const query=new URLSearchParams({title:$("title").value,version:$("version").value});if($("effectiveDate").value)query.set("effective_date",$("effectiveDate").value);result=await api(`/api/contracts/upload?${query}`,{method:"POST",body:form})}else{result=await api("/api/contracts/text",{method:"POST",body:JSON.stringify({title:$("title").value,content:$("content").value,version:$("version").value,effective_date:$("effectiveDate").value||null})})}$("notice").textContent=`Document #${result.id} saved. Opening it now…`;window.location.assign(`/documents/${result.id}`)}catch(error){$("notice").textContent=error.message;button.disabled=false}});
  updateType();loadParents();
