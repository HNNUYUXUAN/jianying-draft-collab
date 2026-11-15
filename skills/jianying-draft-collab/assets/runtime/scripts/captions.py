"""Caption display policy; speech and timestamps remain authoritative."""
import re
TRAILING='，。！？；：、,.!?;:…“”‘’"\''
def display(text):return text.rstrip().rstrip(TRAILING).rstrip()
def clauses(text):
    # Colon and comma are semantic boundaries; preserve decimals and formula tokens.
    return re.findall(r'[^，。！？；：!?;:]+[，。！？；：!?;:]*',text)

def reflow(placement,audit,phrases):
    """Apply host-reviewed semantic boundaries against original native tokens."""
    from pipeline import normalized
    cues=[]
    for item,record in zip(placement['segments'],audit['segments']):
        parts=phrases[item['id']];tokens=record['chars'];cursor=0
        assert re.sub(r'\s+','',''.join(parts))==re.sub(r'\s+','',item['text']),'Caption reflow may split source text, never rewrite signs, decimals or punctuation'
        assert normalized(''.join(parts))==''.join(t['char'] for t in tokens)
        for part in parts:
            count=len(normalized(part));take=tokens[cursor:cursor+count];cursor+=count
            assert take and len(display(part))<=14
            cues.append({'source_text':part,'display_text':display(part),'text':display(part),'start_ms':take[0]['start']+record['offset_ms'],'end_ms':take[-1]['end']+record['offset_ms']})
    return cues
