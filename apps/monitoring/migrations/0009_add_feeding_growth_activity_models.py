from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0008_alter_eventlog_options_alter_sensorreading_options_and_more'),
    ]

    operations = [

        # ── FeedingEvent ──
        migrations.CreateModel(
            name='FeedingEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trigger',          models.CharField(max_length=10, choices=[('AUTO','자동'),('MANUAL','수동')], default='AUTO', help_text='급이 트리거')),
                ('amount_g',         models.FloatField(default=0.0, help_text='급이량(g)')),
                ('growth_stage',     models.CharField(max_length=10, choices=[('FRY','치어 (1~3cm)'),('YOUNG','유어 (3~7cm)'),('ADULT','성어 (7cm+)')], default='FRY', help_text='성장 단계')),
                ('turbidity_before', models.FloatField(default=0.0, help_text='급이 전 탁도(NTU)')),
                ('turbidity_after',  models.FloatField(default=0.0, help_text='급이 후 탁도(NTU)')),
                ('delta_ntu',        models.FloatField(default=0.0, help_text='탁도 변화량(NTU)')),
                ('is_overfeeding',   models.BooleanField(default=False, help_text='과급여 플래그')),
                ('created_at',       models.DateTimeField(auto_now_add=True)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feeding_events', to='monitoring.tank')),
            ],
            options={'app_label': 'monitoring', 'ordering': ['-created_at']},
        ),

        # ── FeedingResponse ──
        migrations.CreateModel(
            name='FeedingResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rt_seconds',      models.FloatField(default=0.0, help_text='반응시간(초)')),
                ('ar_ratio',        models.FloatField(default=0.0, help_text='활동증가율')),
                ('sf_ratio',        models.FloatField(default=0.0, help_text='수면접근빈도')),
                ('frs_score',       models.IntegerField(default=0, help_text='급이 반응 점수(0~100)')),
                ('activity_before', models.FloatField(default=0.0, help_text='급이 전 평균 활동량(px/s)')),
                ('activity_during', models.FloatField(default=0.0, help_text='급이 중 평균 활동량(px/s)')),
                ('activity_after',  models.FloatField(default=0.0, help_text='급이 후 평균 활동량(px/s)')),
                ('created_at',      models.DateTimeField(auto_now_add=True)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feeding_responses', to='monitoring.tank')),
                ('feeding_event', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='response', to='monitoring.feedingevent')),
            ],
            options={'app_label': 'monitoring', 'ordering': ['-created_at']},
        ),

        # ── GrowthRecord ──
        migrations.CreateModel(
            name='GrowthRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fish_id',            models.IntegerField(help_text='ByteTrack 개체 ID')),
                ('size_index',         models.FloatField(help_text='size_index(%)')),
                ('estimated_length',   models.FloatField(default=0.0, help_text='추정 체장(cm)')),
                ('estimated_weight',   models.FloatField(default=0.0, help_text='추정 체중(g)')),
                ('growth_rate',        models.FloatField(default=0.0, help_text='성장률(cm/day)')),
                ('growth_stage',       models.CharField(max_length=10, choices=[('FRY','치어 (1~3cm)'),('YOUNG','유어 (3~7cm)'),('ADULT','성어 (7cm+)')], default='FRY')),
                ('recommended_feed_g', models.FloatField(default=0.0, help_text='권장 1회 급이량(g)')),
                ('created_at',         models.DateTimeField(auto_now_add=True)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='growth_records', to='monitoring.tank')),
            ],
            options={'app_label': 'monitoring', 'ordering': ['-created_at']},
        ),

        # ── ActivityPattern ──
        migrations.CreateModel(
            name='ActivityPattern',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_start',       models.DateTimeField(help_text='분석 시작 시각')),
                ('period_end',         models.DateTimeField(help_text='분석 종료 시각')),
                ('hourly_activity',    models.JSONField(default=dict, help_text='시간대별 평균 활동량')),
                ('baseline_mean',      models.FloatField(default=0.0, help_text='Baseline 평균 속도(px/s)')),
                ('baseline_std',       models.FloatField(default=0.0, help_text='Baseline 표준편차(px/s)')),
                ('current_mean',       models.FloatField(default=0.0, help_text='현재 기간 평균 속도(px/s)')),
                ('deviation_ratio',    models.FloatField(default=0.0, help_text='Baseline 대비 편차 비율')),
                ('daytime_activity',   models.FloatField(default=0.0, help_text='주간 평균 활동량')),
                ('nighttime_activity', models.FloatField(default=0.0, help_text='야간 평균 활동량')),
                ('anomaly_hours',      models.JSONField(default=list, help_text='이상 활동 감지 시간대')),
                ('has_anomaly',        models.BooleanField(default=False)),
                ('created_at',         models.DateTimeField(auto_now_add=True)),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activity_patterns', to='monitoring.tank')),
            ],
            options={'app_label': 'monitoring', 'ordering': ['-created_at']},
        ),

        # ── FishBehavior: abr_score 필드 추가 ──
        migrations.AddField(
            model_name='fishbehavior',
            name='abr_score',
            field=models.FloatField(default=0.0, help_text='이상 행동율(0~1), |speed-μ|>2σ 비율'),
        ),

        # ── Tank: target_temp/ph 기준값 수정 (금붕어 기준) ──
        migrations.AlterField(
            model_name='tank',
            name='target_temp',
            field=models.FloatField(default=22.0, help_text='권장 수온(°C)'),
        ),
        migrations.AlterField(
            model_name='tank',
            name='target_ph',
            field=models.FloatField(default=7.4, help_text='권장 pH'),
        ),
    ]
