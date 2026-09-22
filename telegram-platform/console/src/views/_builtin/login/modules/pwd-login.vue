<script setup lang="ts">
import { computed, onMounted, reactive } from 'vue';
import { useAuthStore } from '@/store/modules/auth';
import { fetchCaptcha } from '@/service/api';
import { useFormRules, useNaiveForm } from '@/hooks/common/form';
import { $t } from '@/locales';

defineOptions({
  name: 'PwdLogin'
});

const authStore = useAuthStore();
const { formRef, validate } = useNaiveForm();

interface FormModel {
  userName: string;
  password: string;
  captcha: string;
}

const model: FormModel = reactive({
  userName: '',
  password: '',
  captcha: ''
});

const captcha = reactive({
  enabled: false,
  uuid: '',
  image: ''
});

async function loadCaptcha() {
  const { data, error } = await fetchCaptcha();
  if (!error && data) {
    captcha.enabled = data.is_enabled;
    captcha.uuid = data.uuid;
    captcha.image = `data:image/jpeg;base64,${data.image}`;
    model.captcha = '';
  }
}

onMounted(loadCaptcha);

const rules = computed<Partial<Record<keyof FormModel, App.Global.FormRule[]>>>(() => {
  const { formRules } = useFormRules();
  return {
    userName: formRules.userName,
    password: formRules.pwd
  };
});

async function handleSubmit() {
  await validate();
  await authStore.login(model.userName, model.password, model.captcha, captcha.uuid);
  if (captcha.enabled) {
    await loadCaptcha();
  }
}
</script>

<template>
  <NForm ref="formRef" :model="model" :rules="rules" size="large" :show-label="false" @keyup.enter="handleSubmit">
    <NFormItem path="userName">
      <NInput v-model:value="model.userName" :placeholder="$t('page.login.common.userNamePlaceholder')" />
    </NFormItem>
    <NFormItem path="password">
      <NInput
        v-model:value="model.password"
        type="password"
        show-password-on="click"
        :placeholder="$t('page.login.common.passwordPlaceholder')"
      />
    </NFormItem>
    <NFormItem v-if="captcha.enabled" path="captcha">
      <div class="w-full flex-y-center gap-12px">
        <NInput v-model:value="model.captcha" class="flex-1" placeholder="验证码" />
        <img :src="captcha.image" alt="captcha" class="h-40px cursor-pointer rounded" @click="loadCaptcha" />
      </div>
    </NFormItem>
    <NButton type="primary" size="large" round block :loading="authStore.loginLoading" @click="handleSubmit">
      {{ $t('common.confirm') }}
    </NButton>
  </NForm>
</template>
