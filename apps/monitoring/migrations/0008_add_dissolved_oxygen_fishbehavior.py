from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0007_sensorreading_turbidity_and_more'),
    ]

    operations = [

        # ── SensorReading: dissolved_oxygen 추가 ──
        migrations.AddField(
            model_name='sensorreading',
            name='dissolved_oxygen',
            field=models.FloatField(default=0.0, help_text='용존산소량(mg/L)'),
        ),

        # ── SensorReading: water_level default 값 변경 ──
        migrations.AlterField(
            model_name='sensorreading',
            name='water_level',
            field=models.FloatField(default=100.0, help_text='수위(%)'),
        ),

        # ── DeviceControl: is_auto 추가 ──
        migrations.AddField(
            model_name='devicecontrol',
            name='is_auto',
            field=models.BooleanField(default=True, help_text='True: 자동 제어 / False: 수동 제어'),
        ),

        # ── DeviceControl: type choices 확장 (COOLING, AIR_PUMP, FEEDER 추가) ──
        migrations.AlterField(
            model_name='devicecontrol',
            name='type',
            field=models.CharField(
                choices=[
                    ('HEATER',   '히터'),
                    ('COOLING',  '냉각팬'),
                    ('FILTER',   '여과기'),
                    ('AIR_PUMP', '에어펌프'),
                    ('FEEDER',   '급이기'),
                    ('LIGHT',    '조명'),
                ],
                max_length=20,
            ),
        ),

        # ── DeviceControl: unique_together 추가 ──
        migrations.AlterUniqueTogether(
            name='devicecontrol',
            unique_together={('tank', 'type')},
        ),

        # ── FishBehavior 모델 신규 생성 ──
        migrations.CreateModel(
            name='FishBehavior',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fish_count',     models.IntegerField(default=0,   help_text='탐지된 개체 수')),
                ('overlap_frames', models.IntegerField(default=0,   help_text='겹침 발생 프레임 수')),
                ('activity_level', models.FloatField(default=0.0,   help_text='활동량(px/frame 이동평균)')),
                ('dominant_zone',  models.CharField(
                    max_length=3, default='MID',
                    choices=[('TOP', '상층'), ('MID', '중층'), ('BOT', '하층')],
                    help_text='주 체류 구역',
                )),
                ('zone_top_ratio', models.FloatField(default=0.0, help_text='상층 체류 비율(0~1)')),
                ('zone_mid_ratio', models.FloatField(default=0.0, help_text='중층 체류 비율(0~1)')),
                ('zone_bot_ratio', models.FloatField(default=0.0, help_text='하층 체류 비율(0~1)')),
                ('size_index',     models.FloatField(default=0.0, help_text='상대 크기 지표(%)')),
                ('feeding_score',  models.IntegerField(default=0, help_text='급이 반응 점수(0~100)')),
                ('status', models.CharField(
                    max_length=10, default='NORMAL',
                    choices=[
                        ('EXCELLENT', '매우 좋음'),
                        ('GOOD',      '좋음'),
                        ('NORMAL',    '보통'),
                        ('WARNING',   '주의'),
                        ('POOR',      '나쁨'),
                    ],
                )),
                ('is_anomaly', models.BooleanField(default=False, help_text='이상 행동 감지 여부')),
                ('note',       models.TextField(blank=True, help_text='AI 권장사항 또는 이상 내용')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tank', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='behaviors',
                    to='monitoring.tank',
                )),
            ],
            options={
                'app_label': 'monitoring',
                'ordering': ['-created_at'],
            },
        ),
    ]
