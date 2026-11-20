"""Bounded readonly native Selection qualification; pure JavaScript constant."""

HASHTAG_CARET_JS = r'''root => {
                        const d={schema:'tag_caret/v2',ok:false,reason:'unknown',rangeCount:0,
                            collapsed:false,focusRoot:document.activeElement===root,
                            anchorType:0,offset:0,length:0,inRoot:false,blocked:false,
                            tailNodes:0,nonformat:false,void:false,unknown:false};
                        const fail=reason=>{d.reason=reason;return d;};
                        if(!root.isConnected || !root.isContentEditable) return fail('root_invalid');
                        const s=document.getSelection();
                        if(!s) return fail('selection_unknown');
                        d.rangeCount=s.rangeCount;d.collapsed=s.isCollapsed;
                        const n=s.anchorNode;d.anchorType=n?n.nodeType:0;
                        d.offset=s.anchorOffset;
                        d.inRoot=!!n && (n===root || root.contains(n));
                        if(!d.focusRoot) return fail('focus_outside');
                        if(s.rangeCount!==1 || !s.isCollapsed || !d.inRoot) return fail('selection_invalid');
                        if(n.nodeType!==1 && n.nodeType!==3) return fail('anchor_unknown');
                        d.length=n.nodeType===3?n.length:n.childNodes.length;
                        if(!Number.isInteger(d.offset) || d.offset<0 || d.offset>d.length) return fail('offset_invalid');
                        const forbidden=el=>el.getAttribute('contenteditable')==='false' ||
                            el.getAttribute('data-slate-void')==='true' ||
                            el.getAttribute('data-slate-inline')==='true' ||
                            /^(topic|hashtag)$/.test(el.getAttribute('data-type')||'');
                        const unknown=el=>!['SPAN','P','DIV','BR'].includes(el.tagName) ||
                            el.hasAttribute('role') || el.hasAttribute('tabindex') || el.hasAttribute('inert') ||
                            Array.from(el.attributes).some(a=>/^on/i.test(a.name));
                        let ancestor=n.nodeType===1?n:n.parentElement,depth=0;
                        for(;ancestor && ancestor!==root && depth<64;ancestor=ancestor.parentElement,depth++) {
                            if(forbidden(ancestor)) {d.blocked=true;return fail('anchor_void');}
                            if(unknown(ancestor)) {d.unknown=true;return fail('anchor_unknown');}
                        }
                        if(ancestor!==root) return fail('ancestor_limit');
                        const original=s.getRangeAt(0);
                        if(!original.collapsed || original.startContainer!==n || original.startOffset!==d.offset ||
                            s.focusNode!==n || s.focusOffset!==d.offset) return fail('range_mismatch');
                        const bounded=document.createTreeWalker(root,NodeFilter.SHOW_ALL);
                        let checked,seen=0,size=0;
                        while((checked=bounded.nextNode())) {
                            if(++seen>2000 || checked.nodeType===3 && (size+=checked.length)>12000)
                                return fail('editor_limit');
                        }
                        const tail=document.createRange();tail.selectNodeContents(root);tail.setStart(n,d.offset);
                        const rest=tail.cloneContents(),walker=document.createTreeWalker(rest,NodeFilter.SHOW_ALL);
                        let node,chars=0;
                        while((node=walker.nextNode())) {
                            if(++d.tailNodes>2000) return fail('tail_limit');
                            if(node.nodeType===3) {
                                if((chars+=node.length)>12000) return fail('tail_text_limit');
                                if(/[^\s\u200b\ufeff]/.test(node.textContent||'')) {
                                    d.nonformat=true;return fail('tail_text');
                                }
                            } else if(node.nodeType===1) {
                                if(forbidden(node)) {d.void=true;return fail('tail_void');}
                                if(unknown(node)) {
                                    d.unknown=true;return fail('tail_unknown');
                                }
                            } else {d.unknown=true;return fail('tail_unknown');}
                        }
                        d.ok=true;d.reason='logical_end';return d;
                    }'''
