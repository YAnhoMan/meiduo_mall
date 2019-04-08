from django_redis import get_redis_connection
from rest_framework import serializers

from .models import OAuthQQUser
from .utils import check_save_user_token
from users.models import User

from celery_tasks.email.tasks import send_verify_email


class QQAuthUserSerializer(serializers.Serializer):
    """
    QQ登录创建用户序列化器
    """
    access_token = serializers.CharField(label='操作凭证')
    mobile = serializers.RegexField(label='手机号', regex=r'^1[3-9]\d{9}$')
    password = serializers.CharField(label='密码', max_length=20, min_length=8)
    sms_code = serializers.CharField(label='短信验证码')

    def validate(self, attrs):

        access_token = attrs.get('access_token')

        openid = check_save_user_token(access_token)

        if not openid:
            raise serializers.ValidationError('无效的access_token')

        attrs['openid'] = openid

        mobile = attrs['mobile']
        sms_code = attrs['sms_code']

        redis_conn = get_redis_connection('verify_codes')
        real_sms_code = redis_conn.get('sms_%s' % attrs['mobile'])

        if not real_sms_code:
            raise serializers.ValidationError('无效的短信验证码')

        if attrs['sms_code'] != real_sms_code.decode():
            raise serializers.ValidationError('短信验证码错误')

        try:
            user = User.objects.get(mobile=mobile)

        except User.DoesNotExist:
            pass

        else:
            password = attrs['password']

            if not user.check_password(password):
                raise serializers.ValidationError('密码错误')

            attrs['user'] = user

        return attrs

    def create(self, validated_data):

        user = validated_data.get('user')

        if not user:
            user = User.objects.create_user(
                username=validated_data['mobile'],
                mobile=validated_data['mobile'],
                password=validated_data['password']
            )

        OAuthQQUser.objects.create(
            openid=validated_data['openid'],
            user=user)

        return user


class EmailSerializer(serializers.ModelSerializer):
    """
    邮箱序列号器
    """

    class Meta:
        model = User
        fields = ('id', 'email')
        extra_kwargs = {
            'email': {
                'required': True
            }
        }

    def update(self, instance, validated_data):
        email = validated_data['email']
        instance.email = email
        instance.save()

        # 生成验证链接
        verify_url = instance.generate_verify_email_url()
        # 发送验证邮件
        send_verify_email.delay(email, verify_url)
        return instance
