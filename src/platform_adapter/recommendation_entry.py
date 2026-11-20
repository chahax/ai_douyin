"""Follow the site's visible recommendation link after its /jingxuan redirect."""
NAVIGATION = r'''() => ({host:location.hostname,path:location.pathname,
 links:Array.from(document.querySelectorAll('a')).map((a,index)=>{
   const r=a.getBoundingClientRect(),s=getComputedStyle(a),u=new URL(a.href,location.href);
   return {index,label:(a.innerText||'').trim(),host:u.hostname,protocol:u.protocol,
     visible:r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)!==0};
 }).filter(a=>a.visible&&a.label==='推荐')})'''


def enter_recommendation(page):
    state=page.locator('html').evaluate(NAVIGATION)
    if not isinstance(state,dict) or state.get('host')!='www.douyin.com' or state.get('path')!='/jingxuan':
        return {'clicked':False,'reason':'not_redirected'}
    matches=[a for a in state.get('links',[]) if a.get('label')=='推荐' and a.get('visible') is True
             and a.get('host')=='www.douyin.com' and a.get('protocol')=='https:' and type(a.get('index')) is int]
    if len(matches)!=1:
        return {'clicked':False,'reason':'recommendation_link_ambiguous','matches':len(matches)}
    # Require the same observed DOM link immediately before clicking it.
    again=page.locator('html').evaluate(NAVIGATION)
    if again != state:return {'clicked':False,'reason':'navigation_changed'}
    page.locator('a').nth(matches[0]['index']).click(timeout=3000)
    return {'clicked':True,'reason':'visible_recommendation_link'}
