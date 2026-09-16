from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('monitoring', '0017_fishactivitydetail'),
    ]

    operations = [
        migrations.RenameField(
            model_name='sensorreading',
            old_name='turbidity',
            new_name='tds_ppm',
        ),
        migrations.AlterField(
            model_name='sensorreading',
            name='tds_ppm',
            field=models.FloatField(default=0.0, help_text='총용존고형물(TDS, ppm)'),
        ),
        migrations.AddField(
            model_name='tank',
            name='filter_on_hour',
            field=models.IntegerField(default=0, help_text='여과기 자동 점등 시각(시). ON/OFF가 같으면 24시간 ON'),
        ),
        migrations.AddField(
            model_name='tank',
            name='filter_off_hour',
            field=models.IntegerField(default=0, help_text='여과기 자동 소등 시각(시). ON/OFF가 같으면 24시간 ON'),
        ),
    ]
