from django.contrib import admin
from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display  = ('id', 'user', 'message_preview', 'response_preview', 'created_at')
    list_filter   = ('created_at', 'user')
    search_fields = ('message', 'response', 'user__username')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    def message_preview(self, obj):
        return (obj.message[:40] + '…') if len(obj.message) > 40 else obj.message
    message_preview.short_description = '질문'

    def response_preview(self, obj):
        return (obj.response[:40] + '…') if len(obj.response) > 40 else obj.response
    response_preview.short_description = '응답'