from tortoise import fields, models


# -------------------- Language --------------------
class Language(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=250, unique=True)
    slug = fields.CharField(max_length=250, unique=True, null=True)

    class Meta:
        table = "problems_language"


# -------------------- Problem --------------------
class Problem(models.Model):
    id = fields.IntField(pk=True)
    time_limit = fields.IntField(default=2000, null=True)
    memory_limit = fields.IntField(default=256, null=True)

    class Meta:
        table = "problems_problem"


# -------------------- ExecutionTestCase --------------------
class ExecutionTestCase(models.Model):
    id = fields.IntField(pk=True)
    problem = fields.ForeignKeyField("models.Problem", on_delete=fields.CASCADE, db_column="problem_id")
    language = fields.ForeignKeyField("models.Language", on_delete=fields.CASCADE, db_column="language_id")
    top_code = fields.TextField(null=True)
    bottom_code = fields.TextField()

    class Meta:
        table = "problems_executiontestcase"
        unique_together = (("problem", "language"),)


# -------------------- TestCase --------------------
class TestCase(models.Model):
    id = fields.IntField(pk=True)
    problem = fields.ForeignKeyField("models.Problem", on_delete=fields.CASCADE, db_column="problem_id")
    input_txt = fields.TextField()
    output_txt = fields.TextField()

    class Meta:
        table = "problems_testcase"


# -------------------- Contest --------------------
class Contest(models.Model):
    id = fields.IntField(pk=True)
    title = fields.CharField(max_length=200)
    description = fields.TextField()
    type = fields.CharField(max_length=10, default="open")
    status = fields.CharField(max_length=10, default="upcoming")
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField()
    access_key = fields.CharField(max_length=100, null=True)
    
    class Meta:
        table = "contests_contest"


# -------------------- BaseUser --------------------
class BaseUser(models.Model):
    id = fields.IntField(pk=True)
    telegram_id = fields.BigIntField(unique=True)
    username = fields.CharField(max_length=150, null=True)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "users"


# -------------------- ContestRegistration --------------------
class ContestRegistration(models.Model):
    id = fields.IntField(pk=True)
    # user_id va contest_id orqali Django bilan to'g'ri bog'lanadi
    user = fields.ForeignKeyField("models.BaseUser", on_delete=fields.CASCADE, db_column="user_id")
    contest = fields.ForeignKeyField("models.Contest", on_delete=fields.CASCADE, db_column="contest_id")
    is_active = fields.BooleanField(default=True)
    total_score = fields.IntField(default=0)
    rank = fields.IntField(null=True)

    class Meta:
        table = "contests_contestregistration"
        unique_together = (("user", "contest"),)
# -------------------- Submission --------------------
class Submission(models.Model):
    id = fields.IntField(pk=True)
    
    # ─── FOYDALANUVCHI VA MASALA BOG'LANISHLARI ───
    # Django foreign key ustunlari nomiga avtomatik '_id' qo'shadi, db_column orqali moslashtirdik
    user = fields.ForeignKeyField("models.BaseUser", on_delete=fields.CASCADE, db_column="user_id")
    problem = fields.ForeignKeyField("models.Problem", on_delete=fields.CASCADE, db_column="problem_id")
    contest = fields.ForeignKeyField("models.Contest", on_delete=fields.CASCADE, null=True, db_column="contest_id")

    # ─── KOD VA KO'RSATKICHLAR ───
    code = fields.TextField()
    language = fields.ForeignKeyField("models.Language", on_delete=fields.RESTRICT, db_column="language_id")

    # ─── YAKUNIY STATUS (Accepted / Wrong Answer) ───
    status = fields.BooleanField(default=False, db_index=True)

    # ─── RAMda BAJARILGAN TEST CASE NATIJALARI (JSON FORMATDA) ───
    test_results = fields.JSONField(default=list)
    
    # ─── VAQT KO'RSATKICHI ───
    submitted_at = fields.DatetimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        table = "submissions_submission"  # Django: submissions_submission
        ordering = ["-submitted_at"]
        
        # ⚡ Tortoise-ORM da kompozit indekslar (Composite Indexes) quyidagicha yoziladi
        indexes = [
            ("user_id", "problem_id", "status"),
            ("user_id", "contest_id"),
            ("status", "submitted_at"),
            ("contest_id", "status"),
        ]

    def __str__(self):
        status_text = "Accepted ✓" if self.status else "Failed ✗"
        return f"Submission {self.id} - {status_text}"

# -------------------- UserStats --------------------
class UserStats(models.Model):
    id = fields.IntField(pk=True)
    user = fields.OneToOneField("models.BaseUser", related_name="stats", on_delete=fields.CASCADE, db_column="user_id")
    xp = fields.IntField(default=0, db_index=True)
    level = fields.IntField(default=1)
    
    easy_count = fields.IntField(default=0)
    medium_count = fields.IntField(default=0)
    hard_count = fields.IntField(default=0)
    test_count = fields.IntField(default=0)
    total_solved = fields.IntField(default=0)

    current_streak = fields.IntField(default=0)
    last_activity = fields.DateField(null=True)
    
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "status_userstats"  # Django: status_userstats


# -------------------- LessonStatus --------------------
class LessonStatus(models.Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.BaseUser", on_delete=fields.CASCADE, db_column="user_id")
    lesson_id = fields.IntField()  # Katta relyatsiya shart emas, faqat ID yetarli
    is_completed = fields.BooleanField(default=False)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "status_lessonstatus"
        unique_together = (("user", "lesson_id"),)


# -------------------- UserActivityDaily --------------------
class UserActivityDaily(models.Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.BaseUser", on_delete=fields.CASCADE, db_column="user_id")
    date = fields.DateField(db_index=True)
    xp_earned = fields.IntField(default=0)
    problems_count = fields.IntField(default=0)
    total_duration = fields.IntField(default=0)

    class Meta:
        table = "status_useractivitydaily"
        unique_together = (("user", "date"),)
