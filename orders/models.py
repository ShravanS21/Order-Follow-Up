from django.db import models

class Order(models.Model):
    order_id = models.CharField(max_length=100, primary_key=True)
    order_date = models.DateTimeField(null=True, blank=True)
    customer_name = models.CharField(max_length=200, null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)
    order_value = models.FloatField(null=True, blank=True)
    payment_type = models.CharField(max_length=30, null=True, blank=True)
    status = models.CharField(max_length=40, null=True, blank=True)
    dispatch_date = models.DateTimeField(null=True, blank=True)
    expected_delivery = models.DateTimeField(null=True, blank=True)
    assigned_employee = models.CharField(max_length=150, null=True, blank=True)
    has_issues = models.BooleanField(default=False)
    upload = models.ForeignKey("Upload", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")

    def __str__(self):
        return self.order_id

class Upload(models.Model):
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField()
    uploaded_by = models.CharField(max_length=150)
    rows_total = models.PositiveIntegerField()
    rows_imported = models.PositiveIntegerField(default=0)
    rows_rejected = models.PositiveIntegerField(default=0)
    issue_count = models.PositiveIntegerField(default=0)

class DataIssue(models.Model):
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE, related_name="issues")
    row_no = models.PositiveIntegerField()
    order_id = models.CharField(max_length=100, blank=True)
    issue_type = models.CharField(max_length=80)
    detail = models.TextField()

class Task(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="tasks")
    rule_code = models.CharField(max_length=40)
    reason = models.TextField()
    priority = models.CharField(max_length=10)
    assigned_to = models.CharField(max_length=150)
    action = models.TextField()
    deadline = models.DateTimeField()
    status = models.CharField(max_length=20, default="Open")
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "rule_code"], name="one_task_per_order_rule")]
        ordering = ["deadline"]

class AuditEntry(models.Model):
    ts = models.DateTimeField()
    order_id = models.CharField(max_length=100)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    detail = models.TextField()
    user = models.CharField(max_length=150)

class Setting(models.Model):
    key = models.CharField(max_length=40, primary_key=True)
    value = models.CharField(max_length=100)
