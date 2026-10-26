import csv, io, re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import sys
import pandas as pd
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
from rules import RULES, evaluate
from .ai import AIServiceError, generate_customer_draft, generate_daily_brief
from .models import AuditEntry, DataIssue, Order, Setting, Task, Upload

MANAGER = "Suresh Kumar (Manager)"
TASK_STATUSES = ["Open", "In Progress", "Resolved"]
DEFAULTS = {"unconfirmed_hours":"2", "dispatch_hours":"24", "high_value":"5000", "as_of":""}
DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]
STATUS_MAP = {"unconfirmed":"Unconfirmed", "pending":"Unconfirmed", "pending confirmation":"Unconfirmed", "new":"Unconfirmed", "confirmed":"Confirmed", "dispatched":"Dispatched", "shipped":"Dispatched", "in transit":"Dispatched", "out for delivery":"Dispatched", "delivered":"Delivered", "completed":"Delivered", "failed delivery":"Failed Delivery", "delivery failed":"Failed Delivery", "failed":"Failed Delivery", "ndr":"Failed Delivery", "undelivered":"Failed Delivery", "cancelled":"Cancelled", "canceled":"Cancelled"}
ALIASES = {"phone":"phone_number", "status":"order_status", "expected_delivery":"expected_delivery_date", "employee":"assigned_employee", "customer":"customer_name", "value":"order_value", "payment":"payment_type", "date":"order_date"}
REQUIRED = ["order_id","order_date","customer_name","phone_number","order_value","payment_type","order_status","dispatch_date","expected_delivery_date","assigned_employee"]

def real_ts(): return datetime.now().replace(microsecond=0)
def cfg():
    v={**DEFAULTS,**dict(Setting.objects.values_list("key","value"))}
    return {"unconfirmed_hours":float(v["unconfirmed_hours"]),"dispatch_hours":float(v["dispatch_hours"]),"high_value":float(v["high_value"]),"as_of":v["as_of"]}
def now_for(c=None):
    c=c or cfg(); return datetime.strptime(c["as_of"],"%Y-%m-%d %H:%M") if c["as_of"] else datetime.now().replace(microsecond=0)
def current_user(request): return request.session.get("user",MANAGER)
def employee_names():
    a=Order.objects.exclude(assigned_employee__isnull=True).exclude(assigned_employee="").values_list("assigned_employee",flat=True)
    b=Task.objects.exclude(assigned_to="Unassigned").values_list("assigned_to",flat=True)
    return sorted(set(a)|set(b))
def build_app_context(request):
    c=cfg(); user=current_user(request)
    return {"RULES":RULES,"MANAGER":MANAGER,"TASK_STATUSES":TASK_STATUSES,"PRIORITIES":["High","Medium","Low"],"users":[MANAGER]+employee_names(),"current_user":user,"is_manager":user==MANAGER,"cfg":c,"cfg_as_of_input":c["as_of"].replace(" ","T"),"now":now_for(c),"nav_items":[("dashboard","Dashboard"),("tasks","Tasks"),("report","Daily report"),("audit","Audit trail"),("upload","Upload data"),("settings","Rules & settings")]}
def audit(order_id,action,detail,user,task=None): AuditEntry.objects.create(ts=real_ts(),order_id=order_id,task=task,action=action,detail=detail,user=user)
def parse_date(s,eod=False):
    for fmt in DATE_FORMATS:
        try:
            d=datetime.strptime(s,fmt)
            return d.replace(hour=23,minute=59,second=59) if eod and "%H" not in fmt else d
        except ValueError: pass
    raise ValueError(s)

def read_upload(file):
    if file.name.lower().endswith(".csv"):
        raw=file.read()
        try: text=raw.decode("utf-8-sig")
        except UnicodeDecodeError: text=raw.decode("latin-1")
        df=pd.read_csv(io.StringIO(text),dtype=str,keep_default_na=False)
    elif file.name.lower().endswith((".xlsx",".xls")): df=pd.read_excel(file,dtype=str).fillna("")
    else: raise ValueError("Unsupported file type. Upload a .csv or .xlsx file.")
    df.columns=[ALIASES.get(c,c) for c in (re.sub(r"[^a-z0-9]+","_",str(x).strip().lower()).strip("_") for x in df.columns)]
    missing=[x for x in REQUIRED if x not in df.columns]
    if missing: raise ValueError("Missing required column(s): "+", ".join(missing))
    if df.empty: raise ValueError("The file has no data rows.")
    return df

@transaction.atomic
def import_orders(df,filename,user):
    upload=Upload.objects.create(filename=filename,uploaded_at=real_ts(),uploaded_by=user,rows_total=len(df)); seen={}; issues=[]; imported=rejected=0
    for i,r in enumerate(df.to_dict("records")):
        no,oid,start=i+2,str(r["order_id"]).strip(),len(issues)
        def issue(kind,detail): issues.append(DataIssue(upload=upload,row_no=no,order_id=oid,issue_type=kind,detail=detail))
        if not oid: issue("Missing field","Order ID is missing; row rejected"); rejected+=1; continue
        if oid in seen: issue("Duplicate order ID",f"Also appears in row {seen[oid]}; this row ignored"); rejected+=1; continue
        seen[oid]=no; name=str(r["customer_name"]).strip()
        if not name: issue("Missing field","Customer name is missing")
        phone=re.sub(r"\D","",str(r["phone_number"]))
        if len(phone)==12 and phone.startswith("91"): phone=phone[2:]
        if not phone: issue("Missing field","Phone number is missing"); phone=None
        elif not re.fullmatch(r"[6-9]\d{9}",phone): issue("Invalid value",f"Phone '{r['phone_number']}' is not a valid 10-digit mobile number"); phone=None
        raw=str(r["order_value"]).strip(); value=None
        if not raw: issue("Missing field","Order value is missing")
        else:
            try:
                value=float(re.sub(r"(?i)[₹,\s]|rs\.?","",raw))
                if value<=0: raise ValueError()
            except ValueError: issue("Invalid value",f"Order value '{raw}' is not a positive number"); value=None
        payraw=str(r["payment_type"]).strip().lower(); payment={"prepaid":"Prepaid","cod":"COD"}.get(payraw)
        if not payraw: issue("Missing field","Payment type is missing")
        elif not payment: issue("Invalid value",f"Payment type '{r['payment_type']}' must be Prepaid or COD")
        sraw=str(r["order_status"]).strip(); status=STATUS_MAP.get(re.sub(r"\s+"," ",sraw.lower()))
        if not sraw: issue("Missing field","Order status is missing")
        elif not status: issue("Invalid value",f"Order status '{sraw}' is not recognised")
        employee=str(r["assigned_employee"]).strip()
        if not employee: issue("Missing field","Assigned employee is missing (tasks will go to 'Unassigned')")
        def date_field(col,label,required,eod=False):
            rawdate=str(r[col]).strip()
            if not rawdate:
                if required: issue("Missing field",f"{label} is missing")
                return None
            try: return parse_date(rawdate,eod)
            except ValueError: issue("Invalid date",f"{label} '{rawdate}' is not a valid date"); return None
        od=date_field("order_date","Order date",True); dd=date_field("dispatch_date","Dispatch date",status in ("Dispatched","Delivered","Failed Delivery")); ed=date_field("expected_delivery_date","Expected delivery date",True,True)
        if od and dd and dd<od: issue("Invalid date","Dispatch date is before order date"); dd=None
        if od and ed and ed.date()<od.date(): issue("Invalid date","Expected delivery date is before order date"); ed=None
        Order.objects.update_or_create(order_id=oid,defaults={"order_date":od,"customer_name":name or None,"phone":phone,"order_value":value,"payment_type":payment,"status":status,"dispatch_date":dd,"expected_delivery":ed,"assigned_employee":employee or None,"has_issues":len(issues)>start,"upload":upload}); imported+=1
    DataIssue.objects.bulk_create(issues); upload.rows_imported=imported; upload.rows_rejected=rejected; upload.issue_count=len(issues); upload.save()
    audit("-","FILE_UPLOADED",f"{filename}: {len(df)} rows, {imported} imported, {rejected} rejected, {len(issues)} data issue(s)",user)
    return {"imported":imported,"rejected":rejected,"issues":len(issues)}

@transaction.atomic
def run_rules(user):
    c=cfg(); now=now_for(c); triggered=set(); created=auto=0
    for o in Order.objects.all():
        data={"status":o.status,"order_date":o.order_date,"dispatch_date":o.dispatch_date,"expected_delivery":o.expected_delivery,"order_value":o.order_value,"payment_type":o.payment_type}
        for h in evaluate(data,c,now):
            key=(o.order_id,h["rule"]); triggered.add(key)
            if Task.objects.filter(order=o,rule_code=h["rule"]).exists(): continue
            assignee=o.assigned_employee or "Unassigned"; t=Task.objects.create(order=o,rule_code=h["rule"],reason=h["reason"],priority=h["priority"],assigned_to=assignee,action=h["action"],deadline=h["since"]+timedelta(hours=h["grace_hours"]),status="Open",created_at=real_ts(),updated_at=real_ts())
            audit(o.order_id,"TASK_ASSIGNED",f"{RULES[h['rule']]} ({h['priority']}): assigned to {assignee}",f"system (run by {user})",t); created+=1
    for t in Task.objects.exclude(status="Resolved").select_related("order"):
        if (t.order_id,t.rule_code) not in triggered:
            old=t.status; t.status="Resolved"; t.updated_at=real_ts(); t.save(update_fields=["status","updated_at"]); audit(t.order_id,"STATUS_CHANGE",f"{old} -> Resolved (auto: condition no longer applies, order is now '{t.order.status}')",f"system (run by {user})",t); auto+=1
    return created,auto

def fetch_tasks(params,now=None):
    now=now or now_for(); qs=Task.objects.select_related("order")
    for key,lookup in [("from","order__order_date__date__gte"),("to","order__order_date__date__lte"),("rule","rule_code"),("employee","assigned_to"),("priority","priority"),("status","status")]:
        if params.get(key): qs=qs.filter(**{lookup:params[key]})
    rows=list(qs); rank={"High":0,"Medium":1,"Low":2}; rows.sort(key=lambda t:(rank.get(t.priority,3),t.deadline))
    for t in rows:
        t.overdue=t.status!="Resolved" and t.deadline<now; t.customer_name=t.order.customer_name or "(name missing)"; t.phone=t.order.phone or "(phone missing)"; t.payment_type=t.order.payment_type or "payment missing"; t.value_text=f"₹{t.order.order_value:,.0f}" if t.order.order_value is not None else "₹ (value missing)"; t.order_value=t.order.order_value; t.order_date=t.order.order_date
    return rows

def employee_summary(tasks):
    out={}
    for t in tasks:
        if t.status=="Resolved": continue
        v=out.setdefault(t.assigned_to,{"pending":0,"overdue":0,"high":0}); v["pending"]+=1; v["overdue"]+=bool(t.overdue); v["high"]+=t.priority=="High"
    return dict(sorted(out.items(),key=lambda x:-x[1]["pending"]))

def dashboard(request):
    now=now_for(); f=request.GET; tasks=fetch_tasks(f,now); unresolved=[t for t in tasks if t.status!="Resolved"]; orders=Order.objects.all()
    if f.get("from"): orders=orders.filter(order_date__date__gte=f["from"])
    if f.get("to"): orders=orders.filter(order_date__date__lte=f["to"])
    by_rule=Counter(t.rule_code for t in unresolved)
    total=orders.count(); bad=orders.filter(has_issues=True).count(); attention=len({t.order_id for t in unresolved}); nopen=sum(t.status=="Open" for t in tasks); nprog=sum(t.status=="In Progress" for t in tasks); noverdue=sum(t.overdue for t in tasks)
    return render(request,"orders/dashboard.html",{"f":f,"total":total,"bad":bad,"attention":attention,"n_open":nopen,"n_prog":nprog,"n_overdue":noverdue,"by_rule":by_rule,"max_rule":max(by_rule.values(),default=1),"emp":employee_summary(tasks),"urgent":[t for t in unresolved if t.priority=="High"][:15],"kpis":[("Total orders uploaded",total,""),("Orders requiring attention",attention,"text-danger"),("Open tasks",nopen,""),("In progress",nprog,""),("Overdue tasks",noverdue,"text-danger"),("Rows needing data correction",bad,"text-warning")]})
def tasks_page(request): return render(request,"orders/tasks.html",{"f":request.GET,"tasks":fetch_tasks(request.GET),"show_status":True})

@require_POST
def ai_draft(request, tid):
    task=get_object_or_404(Task.objects.select_related("order"),pk=tid)
    user=current_user(request)
    if user!=MANAGER and user!=task.assigned_to:
        messages.error(request,"Only the manager or assigned employee can generate a customer draft.")
        return redirect("tasks")
    try:
        draft=generate_customer_draft(task)
    except AIServiceError as exc:
        messages.error(request,str(exc))
        return redirect("tasks")
    audit(task.order_id,"AI_DRAFT_GENERATED","AI customer-message draft generated for employee review",user,task)
    return render(request,"orders/ai_draft.html",{"task":task,"draft":draft})

@require_POST
def ai_daily_brief(request):
    if current_user(request)!=MANAGER:
        messages.error(request,"The daily operations brief is available to the manager.")
        return redirect("dashboard")
    now=now_for()
    tasks=list(Task.objects.exclude(status="Resolved").select_related("order"))
    overdue=[t for t in tasks if t.deadline<now]
    rule_counts=Counter(t.rule_code for t in tasks)
    metrics={
        "as_of":now.strftime("%Y-%m-%d %H:%M"),
        "unresolved_tasks":len(tasks),
        "overdue_tasks":len(overdue),
        "high_priority_tasks":sum(t.priority=="High" for t in tasks),
        "open_tasks":sum(t.status=="Open" for t in tasks),
        "in_progress_tasks":sum(t.status=="In Progress" for t in tasks),
        "by_exception":{RULES[code]:count for code,count in rule_counts.items()},
    }
    try:
        brief=generate_daily_brief(metrics)
    except AIServiceError as exc:
        messages.error(request,str(exc))
        return redirect("dashboard")
    audit("-","AI_DAILY_BRIEF_GENERATED","Anonymized daily operations brief generated",current_user(request))
    return render(request,"orders/ai_brief.html",{"brief":brief,"metrics":metrics})

@require_POST
def update_task(request,tid):
    t=get_object_or_404(Task,pk=tid); user=current_user(request); nxt=request.POST.get("next",""); back=redirect(nxt if nxt.startswith("/") else "tasks")
    status=request.POST.get("status",t.status); assignee=request.POST.get("assigned_to",t.assigned_to)
    if status not in TASK_STATUSES or (assignee!=t.assigned_to and assignee not in [MANAGER]+employee_names()): messages.error(request,"Invalid status or employee."); return back
    overdue=t.status!="Resolved" and t.deadline<now_for(); changed=False
    if assignee!=t.assigned_to:
        if user!=MANAGER: messages.error(request,"Only a manager can reassign tasks."); return back
        old=t.assigned_to; t.assigned_to=assignee; t.updated_at=real_ts(); t.save(); audit(t.order_id,"REASSIGNED",f"{old} -> {assignee}"+(" (task was overdue)" if overdue else ""),user,t); changed=True
    if status!=t.status:
        if user not in (MANAGER,t.assigned_to): messages.error(request,"Only the manager or assigned employee can change status."); return back
        old=t.status; t.status=status; t.updated_at=real_ts(); t.save(); audit(t.order_id,"STATUS_CHANGE",f"{old} -> {status}",user,t); changed=True
    messages.success(request,f"Task for {t.order_id} updated." if changed else "No changes made."); return back

def upload(request):
    if request.method=="POST":
        file=request.FILES.get("file")
        if not file: messages.error(request,"Choose a CSV or Excel file first."); return redirect("upload")
        try:
            result=import_orders(read_upload(file),file.name,current_user(request)); created,auto=run_rules(current_user(request)); messages.success(request,f"{result['imported']} orders imported, {result['rejected']} rows rejected, {result['issues']} data issue(s). {created} new task(s) created, {auto} auto-resolved.")
        except Exception as exc: messages.error(request,f"Could not import file: {exc}")
        return redirect("upload")
    last=Upload.objects.order_by("-id").first()
    return render(request,"orders/upload.html",{"last":last,"issues":last.issues.order_by("row_no") if last else [],"hist":Upload.objects.order_by("-id")[:10],"empty":not Order.objects.exists()})

@require_POST
def load_sample(request):
    sample_path=PROJECT_DIR/"sample_data"/"sample_orders.csv"
    try:
        with sample_path.open("rb") as fh:
            class Sample: name="sample_orders.csv"
            sample=Sample(); sample.read=fh.read
            result=import_orders(read_upload(sample),sample.name,current_user(request))
        Setting.objects.update_or_create(key="as_of",defaults={"value":"2026-10-21 10:00"}); created,auto=run_rules(current_user(request))
        messages.success(request,f"Sample data loaded ({result['imported']} orders, {created} tasks). Clock set to 2026-10-21 10:00.")
    except Exception as exc: messages.error(request,f"Could not load sample data: {exc}")
    return redirect("dashboard")

def report_data():
    now=now_for(); tasks=fetch_tasks({},now); cutoff=datetime.now()-timedelta(hours=24); unresolved=[t for t in tasks if t.status!="Resolved"]
    return {"new":[t for t in tasks if t.created_at>=cutoff],"unresolved":unresolved,"overdue":[t for t in unresolved if t.overdue],"high":[t for t in unresolved if t.priority=="High"],"emp":employee_summary(tasks),"asof":now}
def report(request):
    data=report_data(); data["sections"]=[("New exceptions, last 24 hours",data["new"]),("Unresolved exceptions",data["unresolved"]),("Overdue tasks",data["overdue"]),("High-priority cases",data["high"])]; return render(request,"orders/report.html",data)
def report_csv(request):
    data=report_data(); out=io.StringIO(); writer=csv.writer(out); writer.writerow(["section","task_id","order_id","customer","phone","exception_type","reason","priority","assigned_to","action","deadline","task_status","overdue"])
    for title,key in [("New exceptions (last 24h)","new"),("Unresolved exceptions","unresolved"),("Overdue tasks","overdue"),("High-priority cases","high")]:
        for t in data[key]: writer.writerow([title,t.id,t.order_id,t.customer_name,t.phone,RULES[t.rule_code],t.reason,t.priority,t.assigned_to,t.action,t.deadline.strftime("%Y-%m-%d %H:%M"),t.status,"Yes" if t.overdue else "No"])
    for e,v in data["emp"].items(): writer.writerow(["Employee-wise pending actions","","","","","",f"{v['pending']} pending / {v['overdue']} overdue / {v['high']} high priority","",e,"","",""])
    response=HttpResponse(out.getvalue(),content_type="text/csv"); response["Content-Disposition"]=f"attachment; filename=daily_exception_report_{data['asof']:%Y-%m-%d}.csv"; return response

def audit_page(request):
    q=request.GET.get("q","").strip(); rows=AuditEntry.objects.filter(Q(order_id__icontains=q)|Q(user__icontains=q)|Q(action__icontains=q)).order_by("-id")[:500]
    return render(request,"orders/audit.html",{"rows":rows,"q":q})
def settings_page(request):
    if request.method=="POST":
        if current_user(request)!=MANAGER: messages.error(request,"Only a manager can change business rules."); return redirect("settings")
        try:
            values={k:float(request.POST[k]) for k in ("unconfirmed_hours","dispatch_hours","high_value")}
            if any(v<=0 for v in values.values()): raise ValueError("Values must be greater than zero.")
            as_of=request.POST.get("as_of","").strip().replace("T"," ")
            if as_of: datetime.strptime(as_of,"%Y-%m-%d %H:%M")
            old=cfg()
            for key,value in values.items():
                Setting.objects.update_or_create(key=key,defaults={"value":f"{value:g}"})
                if old[key]!=value: audit("-","RULE_CHANGED",f"{key}: {old[key]:g} -> {value:g}",current_user(request))
            if old["as_of"]!=as_of:
                Setting.objects.update_or_create(key="as_of",defaults={"value":as_of}); audit("-","CLOCK_CHANGED",f"as_of: '{old['as_of'] or 'live clock'}' -> '{as_of or 'live clock'}'",current_user(request))
            created,auto=run_rules(current_user(request)); messages.success(request,f"Settings saved and rules re-run: {created} new task(s), {auto} auto-resolved.")
        except (ValueError,KeyError) as exc: messages.error(request,f"Invalid settings: {exc}")
        return redirect("settings")
    return render(request,"orders/settings.html")

@require_POST
def reset(request):
    if current_user(request)!=MANAGER: messages.error(request,"Only a manager can reset data."); return redirect("settings")
    AuditEntry.objects.all().delete(); Task.objects.all().delete(); DataIssue.objects.all().delete(); Upload.objects.all().delete(); Order.objects.all().delete(); Setting.objects.all().delete()
    messages.info(request,"All data cleared."); return redirect("upload")
@require_POST
def switch_user(request):
    request.session["user"]=request.POST.get("user",MANAGER); nxt=request.POST.get("next","/"); return redirect(nxt if nxt.startswith("/") else "/")
