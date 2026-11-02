
"""Render only approved administrative metadata as SVG; no model, reference, or PDF."""
from pathlib import Path
from xml.sax.saxutils import escape
from datetime import datetime
import json, argparse
from PIL import Image, ImageDraw, ImageFont

HERE=Path(__file__).resolve().parent
DATA=json.loads((HERE/'dados-permitidos.json').read_text())
INK='#142a3b'; MUTED='#42586a'; GRID='#d7e0e7'; PRIMARY='#9b4b16'; SECONDARY='#006b64'
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

class Figure:
 def __init__(self,w,h,title,description):
  self.w=w;self.h=h;self.parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc"><title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>']
  self.im=Image.new('RGB',(w,h),'white');self.draw=ImageDraw.Draw(self.im)
  self.rect(0,0,w,h,'#ffffff')
 def rect(self,x,y,w,h,fill,stroke=None):
  self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"'+(f' stroke="{stroke}"' if stroke else '')+'/>')
  self.draw.rectangle((x,y,x+w,y+h),fill=fill,outline=stroke)
 def line(self,x1,y1,x2,y2,color=GRID,width=2):
  self.parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')
  self.draw.line((x1,y1,x2,y2),fill=color,width=width)
 def circle(self,x,y,r,color):
  self.parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')
  self.draw.ellipse((x-r,y-r,x+r,y+r),fill=color)
 def text(self,x,y,s,size=20,bold=False,color=INK,anchor='start'):
  f=ImageFont.truetype(BOLD if bold else FONT,size)
  box=self.draw.textbbox((0,0),s,font=f,anchor='lt');tw=box[2];th=box[3]
  left=x if anchor=='start' else x-tw/2 if anchor=='middle' else x-tw
  assert left>=0 and left+tw<=self.w+1 and y>=0 and y+th<=self.h+1,(s,left,tw,y,self.w,self.h)
  self.parts.append(f'<text x="{x}" y="{y}" font-family="DejaVu Sans, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{anchor}" dominant-baseline="text-before-edge">{escape(s)}</text>')
  self.draw.text((left,y),s,font=f,fill=color,anchor='lt')
 def lines(self,x,y,lines,size=20,bold=False,color=INK,leading=None):
  for i,s in enumerate(lines):self.text(x,y+i*(leading or size+9),s,size,bold,color)
 def header(self,number,title,subtitle):
  self.text(40,25,number,17,True,SECONDARY)
  self.text(40,55,title,28,True)
  self.text(40,100,subtitle,18,False,MUTED)
 def save(self,name,qa):
  (HERE/(name+'.svg')).write_text('\n'.join(self.parts+['</svg>'])+'\n')
  qa.mkdir(parents=True,exist_ok=True);self.im.save(qa/(name+'.png'))

def n(value,lang):
 s=f'{value:.3f}';return s.replace('.',',') if lang=='pt' else s

def f1(lang,qa):
 pt=lang=='pt';title='Procedimento de uma tentativa' if pt else 'Procedure within one attempt'
 f=Figure(1200,510,title,'Two model turns, one admitted Python execution, and contractual verification.')
 f.header('Fig. 2',title,'Fluxo contratual; nenhuma resposta ou valor científico.' if pt else 'Contractual workflow; no model response or scientific value.')
 boxes=[
  ('Turno 1' if pt else 'Turn 1',['Geração de código','Até 512 tokens'] if pt else ['Code generation','Up to 512 tokens']),
  ('Python',['Uma execução admitida','Até 10 segundos'] if pt else ['One admitted execution','Up to 10 seconds']),
  ('Turno 2' if pt else 'Turn 2',['Objeto final em JSON','Até 2048 tokens'] if pt else ['Final JSON object','Up to 2048 tokens']),
  ('V1–V7',['Verificação contratual','Aceite ou recusa'] if pt else ['Contractual verification','Accept or refuse'])]
 for i,(head,lines) in enumerate(boxes):
  x=40+i*290;f.rect(x,165,250,150,'#f1f5f8',GRID);f.text(x+18,184,head,23,True);f.lines(x+18,235,lines,18)
  if i<3:
   f.line(x+255,238,x+282,238,MUTED,3);f.line(x+273,229,x+282,238,MUTED,3);f.line(x+273,247,x+282,238,MUTED,3)
 f.lines(40,350,['Gate real de tokenização antes de cada geração; contexto 8192 tokens.',
                  'Tempo global: 30 minutos. Selo apenas depois do aceite contratual.',
                  'A M1-R altera a instrução do turno 2; não constitui réplica independente.'] if pt else
                 ['Real tokenization gate before each generation; context 8192 tokens.',
                  'Global time limit: 30 minutes. Seal only after contractual acceptance.',
                  'M1-R changes the turn 2 instruction; it is not an independent replication.'],19,leading=36)
 f.save('F1-procedimento-'+lang,qa)

def f2(lang,qa):
 pt=lang=='pt';title='Primária e secundária: registros operacionais' if pt else 'Primary and secondary runs: operational records'
 f=Figure(1200,890,title,'Admitted and operationally completed counts are shown separately; this is not a scientific comparison.')
 f.header('Fig. 3',title,'Contagens do contrato; aceite não demonstra correção científica.' if pt else 'Contract counts; acceptance does not establish scientific correctness.')
 f.rect(40,145,1120,58,'#edf2f5');f.text(60,160,'Medida' if pt else 'Measure',21,True)
 f.text(670,158,'M1-06',23,True,PRIMARY,'middle');f.text(985,158,'M1-R',23,True,SECONDARY,'middle')
 a=DATA['runs']['06'];z=DATA['runs']['07']
 rows=[
 ('Tentativas admitidas' if pt else 'Admitted attempts',str(a['attempts']),str(z['attempts'])),
 ('Recusas contratuais' if pt else 'Contractual refusals',str(a['refusals']),str(z['refusals'])),
 ('Tokenizações (admitidas / concluídas)' if pt else 'Tokenizations (admitted / completed)',f"{a['tokenizations_released']} / {a['tokenizations_successful']}",f"{z['tokenizations_released']} / {z['tokenizations_successful']}"),
 ('Gerações (admitidas / concluídas)' if pt else 'Generations (admitted / completed)',f"{a['generations_released']} / {a['generations_successful']}",f"{z['generations_released']} / {z['generations_successful']}"),
 ('Python (admitidas / concluídas)' if pt else 'Python (admitted / completed)',f"{a['python_executions_released']} / {a['python_completed']}",f"{z['python_executions_released']} / {z['python_completed']}"),
 ('Erros Python' if pt else 'Python errors',str(a['execution_error_counter']),str(z['execution_error_counter'])),
 ('Verificação alcançada' if pt else 'Verification reached','2 × V1; T3: sem V1' if pt else '2 × V1; A3: no V1','V1–V7'),
 ('Desfecho' if pt else 'Outcome','Inconclusiva' if pt else 'Inconclusive','Aceite contratual' if pt else 'Contractual acceptance')]
 for i,(label,left,right) in enumerate(rows):
  y=214+i*43;f.line(40,y+36,1160,y+36);f.text(60,y,label,18);f.text(670,y,left,18,False,PRIMARY,'middle');f.text(985,y,right,18,False,SECONDARY,'middle')
 f.text(40,590,'Tempo nativo global / limite autorizado: 1800 s' if pt else 'Native global elapsed time / authorized limit: 1800 s',20,True)
 for i,(run,color,label) in enumerate([(a,PRIMARY,'M1-06'),(z,SECONDARY,'M1-R')]):
  y=639+i*75;f.text(40,y,label,18,True,color);f.rect(170,y,780,25,'#e9eef2')
  f.rect(170,y,min(780,780*run['state_native_elapsed_seconds']/1800),25,color)
  f.line(950,y-8,950,y+34,INK,2);f.text(980,y,n(run['state_native_elapsed_seconds'],lang)+' s',20,True,color)
 f.lines(40,800,['M1-06: o tempo inclui encerramento após o teto; não é extensão do orçamento.',
                  'T3 = tentativa 3: falha de captura na geração do turno 2, antes de verificação.'] if pt else
                 ['M1-06: elapsed time includes shutdown after the cap; the budget was not extended.',
                  'A3 = attempt 3: capture failure during turn 2 generation, before verification.'],18,leading=32)
 f.save('F2-operacoes-'+lang,qa)

def f3(lang,qa):
 pt=lang=='pt';title='M1-06: eventos registrados nas três tentativas' if pt else 'M1-06: recorded events across three attempts'
 f=Figure(1200,750,title,'UTC times are receipt events, not complete attempt boundaries; refusal timestamps are unavailable.')
 f.header('Fig. S1',title,'2 nov. 2026, UTC. Horários dos recibos; não são os limites completos das tentativas.' if pt else '2 Nov 2026, UTC. Receipt timestamps are not complete attempt boundaries.')
 start=datetime.fromisoformat('2026-11-02T07:45:00+00:00');end=datetime.fromisoformat('2026-11-02T08:16:00+00:00')
 def xx(t):return 145+960*(t-start).total_seconds()/(end-start).total_seconds()
 for i in range(7):
  minute=i*5;t=start.timestamp()+minute*60;x=xx(datetime.fromtimestamp(t,start.tzinfo))
  f.line(x,180,x,590,GRID);f.text(x,605,datetime.fromtimestamp(t,start.tzinfo).strftime('%H:%M'),17,False,MUTED,'middle')
 ops=sorted(DATA['runs']['06']['operations'],key=lambda op:op['utc'])
 for i in range(3):
  y=235+i*140;label=('Tentativa ' if pt else 'Attempt ')+str(i+1)
  outcome=('V1_chaves: recusa' if pt else 'V1_chaves: refusal') if i<2 else ('Falha de captura, antes de V1' if pt else 'Capture failure, before V1')
  f.text(40,y-79,label+' — '+outcome,19,True,PRIMARY)
  segment=[o for o in ops if o['attempt_id']==DATA['runs']['06']['used'][i]];assert [o['operation'] for o in segment]==['tokenize_m1_t1','completion_m1_t1','tokenize_m1_t2','completion_m1_t2'];times=[datetime.fromisoformat(o['utc'].replace('Z','+00:00')) for o in segment]
  f.line(xx(times[0]),y,xx(times[-1]),y,PRIMARY,3)
  for j,(o,t) in enumerate(zip(segment,times)):
   x=xx(t);color=PRIMARY if o['success'] else '#a32530'
   if o['success']:f.circle(x,y,6,color)
   else:f.rect(x-7,y-7,14,14,color)
   yy=y-49 if j%2==0 else y+17;f.text(x,yy,('Tok' if j%2==0 else 'Gen')+' T'+str(1 if j<2 else 2),16,True,color,'middle')
   f.text(x,yy+22,t.strftime('%H:%M:%S'),16,False,INK,'middle')
 f.lines(40,665,['Tok = tokenização; Gen = geração. Segundos completos exibidos; microssegundos no ledger.',
                  'O instante das recusas não foi registrado. Terceira geração T2: timeout do supervisor.'] if pt else
                 ['Tok = tokenization; Gen = generation. Whole seconds displayed; microseconds in the ledger.',
                  'Refusal timestamps were not recorded. Third T2 generation: supervisor timeout.'],17,leading=30)
 f.save('F3-tentativas-'+lang,qa)

def f4(lang,qa):
 pt=lang=='pt';title='Sequência documental e fronteira de custódia' if pt else 'Documentary sequence and custody boundary'
 f=Figure(1200,735,title,'Documentary ordering without a proportional time scale; only the fact of guardian comparison is recorded.')
 f.header('Fig. S2',title,'Ordem documental; espaçamento não representa tempo decorrido.' if pt else 'Documentary order; spacing does not represent elapsed time.')
 rows=[
 ('Contrato congelado' if pt else 'Contract frozen','01 nov. 2026 · 14:29:55 UTC' if pt else '1 Nov 2026 · 14:29:55 UTC','Antes das corridas; identidade do contrato preservada.' if pt else 'Before the runs; contract identity preserved.'),
 ('Primária M1-06' if pt else 'Primary M1-06','02 nov. · término observado 08:18:27 UTC' if pt else '2 Nov · completion observed 08:18:27 UTC','Inconclusiva; estado nativo incidente; sem selo.' if pt else 'Inconclusive; native incident state; no seal.'),
 ('Secundária M1-R' if pt else 'Secondary M1-R','02 nov. · término observado 09:53:31 UTC' if pt else '2 Nov · completion observed 09:53:31 UTC','Aceite contratual na primeira tentativa; não independente.' if pt else 'Contractual acceptance on first attempt; not independent.'),
 ('Corpo cego v2 congelado' if pt else 'Blinded body v2 frozen','02 nov. · 09:57:52 UTC' if pt else '2 Nov · 09:57:52 UTC','Depois da secundária e antes de qualquer comparação.' if pt else 'After the secondary run and before any comparison.'),
 ('Comparação concluída pelo dono' if pt else 'Owner completed the comparison','Depois do congelamento v2; horário não informado.' if pt else 'After the v2 freeze; time not supplied.','Somente fato comunicado; conteúdo e resultado fora do projeto.' if pt else 'Only completion reported; contents and outcome outside the project.')]
 f.line(63,178,63,612,GRID,3)
 for i,(head,time,note) in enumerate(rows):
  y=150+i*105;f.circle(63,y+22,11,SECONDARY if i in [0,3,4] else PRIMARY)
  f.text(96,y,head,22,True);f.text(96,y+34,time,18,False,MUTED);f.text(96,y+62,note,18)
 f.text(40,698,'Nenhuma referência, valor científico ou resultado comparativo é exibido.' if pt else 'No reference, scientific value, or comparative outcome is shown.',18,False,MUTED)
 f.save('F4-cronologia-'+lang,qa)

def arrow(f,x1,y1,x2,y2,color=MUTED,width=3):
 f.line(x1,y1,x2,y2,color,width)
 if y1==y2:
  d=1 if x2>x1 else -1
  f.line(x2-9*d,y2-8,x2,y2,color,width);f.line(x2-9*d,y2+8,x2,y2,color,width)
 else:
  d=1 if y2>y1 else -1
  f.line(x2-8,y2-9*d,x2,y2,color,width);f.line(x2+8,y2-9*d,x2,y2,color,width)

def dashed_rect(f,x,y,w,h,fill,stroke):
 f.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="2" stroke-dasharray="8 6"/>')
 f.draw.rectangle((x,y,x+w,y+h),fill=fill)
 for xx in range(x,x+w,14):
  f.draw.line((xx,y,min(xx+8,x+w),y),fill=stroke,width=2);f.draw.line((xx,y+h,min(xx+8,x+w),y+h),fill=stroke,width=2)
 for yy in range(y,y+h,14):
  f.draw.line((x,yy,x,min(yy+8,y+h)),fill=stroke,width=2);f.draw.line((x+w,yy,x+w,min(yy+8,y+h)),fill=stroke,width=2)

def dashed_vline(f,x,y1,y2,color):
 f.parts.append(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="3" stroke-dasharray="8 6"/>')
 for yy in range(y1,y2,14):f.draw.line((x,yy,x,min(yy+8,y2)),fill=color,width=3)

def box(f,x,y,w,h,title,lines,fill,stroke):
 f.rect(x,y,w,h,fill,stroke);f.text(x+16,y+14,title,19,True);f.lines(x+16,y+50,lines,16,leading=25)

def f0(lang,qa):
 pt=lang=='pt';RED='#a32530'
 f=Figure(1200,800,'Arquitetura do sistema' if pt else 'System architecture','Roles, flows, controls and blinding boundary; no addresses, keys or code.')
 f.header('Fig. 1','Arquitetura do sistema e fronteira de cegamento' if pt else 'System architecture and blinding boundary',
  'Papéis, fluxos e controles; sem endereços, chaves ou código.' if pt else 'Roles, flows, and controls; no addresses, keys, or code.')
 for x,s in [(40,'HUMANO' if pt else 'HUMAN'),(435,'AGENTES DE IA' if pt else 'AI AGENTS'),(830,'CONTROLE, EXECUÇÃO E REGISTROS' if pt else 'CONTROL, EXECUTION, AND RECORDS')]:
  f.text(x,140,s,15,True,MUTED)
 box(f,40,175,330,185,'Dono (humano)' if pt else 'Owner (human)',
  ['Decide e assina os atos','Guardião: escolheu a etapa','Separa material permitido','e reservado','Repassa mensagens'] if pt else
  ['Decides and signs acts','Guardian: selected the step','Separates permitted and','restricted material','Relays messages'],'#fdf3ea',PRIMARY)
 dashed_rect(f,40,470,330,170,'#fbeeee',RED)
 f.text(56,484,'Custódia (só o dono)' if pt else 'Custody (owner only)',19,True)
 f.lines(56,520,['Referência publicada','Comparação após o selo','Anexo escrito pelo dono','Nada volta aos agentes'] if pt else
  ['Published reference','Comparison after the seal','Appendix written by owner','Nothing returns to agents'],16,leading=25)
 arrow(f,205,360,205,468);f.text(216,402,'guarda a referência' if pt else 'keeps the reference',14,False,MUTED)
 dashed_vline(f,402,455,655,RED)
 f.text(40,652,'fronteira de cegamento' if pt else 'blinding boundary',14,True,RED)
 box(f,435,225,330,120,'Codex — construção' if pt else 'Codex — building',
  ['Código, testes e textos','Dispara o comando fixado'] if pt else ['Code, tests, and drafts','Launches the fixed command'],'#f1f5f8',GRID)
 box(f,435,370,330,120,'Claude — revisão' if pt else 'Claude — review',
  ['Pareceres assinados (SSH)','Coordena a sequência'] if pt else ['Signed reviews (SSH)','Coordinates the sequence'],'#f1f5f8',GRID)
 box(f,435,515,330,120,'Antigravity — revisão' if pt else 'Antigravity — review',
  ['Revisão independente do','fechamento, por pacotes'] if pt else ['Independent closure review,','in packets'],'#f1f5f8',GRID)
 box(f,830,175,330,190,'Juiz automático + CI' if pt else 'Automatic judge + CI',
  ['Plano congelado por hash','Fichas de aceite executáveis','Corrida: ato do dono, parecer','do Claude e bytes fixados','Fechar o bloco: + 2 revisões'] if pt else
  ['Plan frozen by hash','Executable acceptance cards','Run: owner act, Claude review,','and pinned bytes','Close block: + 2 reviews'],'#eaf4f3',SECONDARY)
 box(f,830,400,330,150,'Execução isolada (VPS, CPU)' if pt else 'Isolated run (VPS, CPU)',
  ['Qwen3.5-9B Q4_K_M, llama.cpp','Sem rede; sem privilégios','Python até 10 s; V1–V7'] if pt else
  ['Qwen3.5-9B Q4_K_M, llama.cpp','Offline; unprivileged','Python up to 10 s; V1–V7'],'#eaf4f3',SECONDARY)
 box(f,830,590,330,110,'Registros (Git privado)' if pt else 'Records (private Git)',
  ['Commits assinados e hashes','Recibos de cada operação'] if pt else ['Signed commits and hashes','Receipts for each operation'],'#eaf4f3',SECONDARY)
 arrow(f,370,195,828,195);f.text(600,170,'atos assinados' if pt else 'signed acts',14,False,MUTED,'middle')
 arrow(f,765,285,828,285)
 f.line(765,430,797,430,MUTED,3);f.line(765,575,797,575,MUTED,3);f.line(797,575,797,320,MUTED,3);arrow(f,797,320,828,320)
 arrow(f,995,365,995,398);f.text(1006,371,'libera' if pt else 'releases',14,False,MUTED)
 arrow(f,995,550,995,588);f.text(1006,558,'recibos' if pt else 'receipts',14,False,MUTED)
 f.text(40,722,'Setas: atos, candidatas e pareceres entram no juiz; o juiz libera a execução; a execução gera recibos.' if pt else
  'Arrows: acts, candidates, and reviews enter the judge; the judge releases execution; execution produces receipts.',15,False,MUTED)
 f.text(40,747,'A corrida exige ato do dono e parecer do Claude; as duas revisões externas fecham o bloco depois.' if pt else
  'A run requires an owner act and a Claude review; the two external reviews close the block afterwards.',15,False,MUTED)
 f.text(40,772,'Pedidos e pareceres ficam em arquivos versionados; o dono repassa as mensagens entre as conversas.' if pt else
  'Requests and reviews are kept in versioned files; the owner relays messages between the conversations.',15,False,MUTED)
 f.save('F0-arquitetura-'+lang,qa)

def main():
 p=argparse.ArgumentParser();p.add_argument('--qa-dir',required=True);args=p.parse_args();qa=Path(args.qa_dir)
 for lang in ['pt','en']:
  for make in [f0,f1,f2,f3,f4]:make(lang,qa)
 print(json.dumps({'svg_count':10,'qa_png_count':10,'source':'dados-permitidos.json','no_model_or_reference':True}))
if __name__=='__main__':main()
