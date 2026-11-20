"""Question-driven whole-book lexical retrieval, with a strict narrative boundary.

Ranked hits are evidence candidates, not proof of exhaustive recall or semantics.
Later chapters are recorded separately and never silently become current facts.
"""
import math,re
from collections import Counter
from . import contracts as c

def tokens(text):
    chunks=re.findall(r'[\u4e00-\u9fff]+|[A-Za-z0-9]+',text.lower())
    return [token for chunk in chunks for token in ([chunk] if len(chunk)<2 or chunk.isascii() else [chunk[i:i+2] for i in range(len(chunk)-1)])]

def question_schema(target_ids):
    return c.obj(questions=c.array(c.obj(id=c.TEXT,question=c.TEXT,search_terms=c.array(c.TEXT,1),
        target_ids=c.refs(target_ids),purpose=c.choices(['cause','identity','relationship','continuity','knowledge','speaker']))))

class BookIndex:
    def __init__(self,source):
        self.source_sha256=c.digest(source);self.catalog=c.catalog(source);self.keys=list(self.catalog)
        self.order={key:i for i,key in enumerate(self.keys)}
        self.docs={key:Counter(tokens(row['text'])) for key,row in self.catalog.items()}
        self.df=Counter(token for doc in self.docs.values() for token in doc)
        self.average=sum(sum(doc.values()) for doc in self.docs.values())/max(1,len(self.docs))

    def search(self,terms,before_id,limit=6):
        if before_id not in self.order or not terms or any(not t.strip() for t in terms):raise ValueError('invalid_query_boundary')
        query=set(tokens(' '.join(terms)));ranked=[];n=len(self.docs)
        for key,doc in self.docs.items():
            length=sum(doc.values());score=0.0
            for token in query & doc.keys():
                idf=math.log(1+(n-self.df[token]+0.5)/(self.df[token]+0.5));tf=doc[token]
                score+=idf*tf*2.2/(tf+1.2*(0.25+0.75*length/max(1,self.average)))
            if score>0:
                score+=sum(2 for term in terms if term in self.catalog[key]['text'])
                ranked.append((score,key))
        ranked.sort(key=lambda x:(-x[0],self.order[x[1]]))
        cut=self.order[before_id]
        earlier=[{'id':key,'score':round(score,6)} for score,key in ranked if self.order[key]<cut][:limit]
        later=[{'id':key,'score':round(score,6)} for score,key in ranked if self.order[key]>=cut][:limit]
        expanded=[]
        for row in earlier:
            idx=self.order[row['id']];chapter=self.catalog[row['id']]['chapter']
            for k in self.keys[max(0,idx-2):min(cut,idx+3)]:
                if self.catalog[k]['chapter']==chapter and k not in expanded:expanded.append(k)
        return {'terms':terms,'before_id':before_id,'source_sha256':self.source_sha256,
            'earlier_hits':earlier,'eligible_context_ids':expanded,'later_hits_for_review_only':later,
            'exhaustive_recall_claimed':False}

def selection_schema(questions,searches,target_ids=()):
    def ids_schema(ids):
        return c.refs(ids,minimum=0) if ids else {'type':'array','maxItems':0,'items':{'type':'string'}}
    visible=list(dict.fromkeys([key for result in searches.values() for key in result['eligible_context_ids']]+list(target_ids)))
    return c.obj(**{q['id']:c.obj(evidence_ids=ids_schema(visible),
        status=c.choices(['supported','unknown'])) for q in questions})

def validate_selection(questions,searches,selected,target_ids=()):
    issues=c.schema_issues(selected,selection_schema(questions,searches,target_ids),'question_selection')
    if issues:raise c.ContractError(issues)
    for q in questions:
        value=selected[q['id']]
        if value['status']=='supported' and not value['evidence_ids']:raise ValueError('support_requires_evidence')
    return selected

def validate_links(candidate,allowed_ids):
    for link in candidate['source_links']:
        if link['source_id'] not in allowed_ids or not link['screenplay_quote'] or link['screenplay_quote'] not in candidate['screenplay']:
            raise ValueError('invalid_candidate_source_link')
    return candidate
