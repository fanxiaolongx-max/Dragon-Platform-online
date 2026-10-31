/* Create an independent report from the curated platform template; saved documents are never migrated here. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AiReportDefaults=api;})(typeof window==='object'?window:globalThis,function(){
    'use strict';
    function create(source,month){
        if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(month||''))throw new Error('Invalid report month');
        if(!source?.template||!Array.isArray(source.chapters)||!source.chapters.length)throw new Error('Default report template is invalid');
        const doc=JSON.parse(JSON.stringify(source));
        doc.id='';doc.updatedAt='';doc.reportMonth=month;
        const [year,m]=month.split('-').map(Number),next=new Date(Date.UTC(year,m,1));
        for(const field of doc.template.meta){
            const label=typeof field.label==='string'?field.label:field.label?.zh;
            if(label==='报告时间'||label==='数据月份'){
                const value=label==='数据月份'?month.replace('-',''):String(next.getUTCFullYear()).padStart(4,'0')+String(next.getUTCMonth()+1).padStart(2,'0');
                field.value={zh:value,en:value};
            }
        }
        return doc;
    }
    return {create};
});
