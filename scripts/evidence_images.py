"""Render an evidence chart from a measured report and a text-only social card."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]

def font(size,bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/'+('segoeuib.ttf' if bold else 'segoeui.ttf'),size)

def social():
    im=Image.new('RGB',(1280,640),'#0d1727'); d=ImageDraw.Draw(im)
    d.rectangle((0,0,16,640),fill='#42d3ad')
    d.text((70,55),'IT OPS LAB',font=font(28,True),fill='#42d3ad')
    d.text((70,140),'Measured local RAG',font=font(64,True),fill='white')
    d.text((70,238),'Service desk automation with evaluation evidence',font=font(30),fill='#becbdf')
    for x,label in [(70,'70 labelled questions'),(475,'4 retrieval variants'),(875,'CI regression gate')]:
        d.rounded_rectangle((x,345,x+335,440),radius=12,fill='#1d2b40')
        d.text((x+20,374),label,font=font(24,True),fill='white')
    d.text((70,535),'Nazmul Hassan  |  github.com/iamnajib71/it-ops-lab',font=font(25),fill='#becbdf')
    im.save(ROOT/'docs/social-preview.png')

def chart():
    reports=sorted((ROOT/'eval/results').glob('*-retrieval.json'))
    report=json.loads(reports[-1].read_text()); data=report['summary']['all']
    im=Image.new('RGB',(1280,640),'#0d1727'); d=ImageDraw.Draw(im)
    d.text((55,30),'Measured retrieval | 60 answerable questions',font=font(36,True),fill='white')
    d.text((55,85),'Article recall within the first 5 chunks; real local run',font=font(24),fill='#becbdf')
    for i,(name,m) in enumerate(data.items()):
        y=150+i*90
        d.text((55,y),name,font=font(27,True),fill='white')
        d.rounded_rectangle((255,y,255+int(700*m['recall@5']),y+42),radius=8,fill='#42d3ad')
        d.text((990,y),f"{m['recall@5']:.4f}",font=font(27,True),fill='white')
    d.text((55,555),f"{report['provenance']['utc'][:10]} UTC | nomic-embed-text + qwen2.5:3b | see raw JSON",font=font(22),fill='#becbdf')
    im.save(ROOT/'docs/img/retrieval-results.png')

if __name__=='__main__': social(); chart()
