<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { registerAPI, loginAPI } from '@/api/user'
import { useUserStore } from '@/stores/user'

const form$ = ref(null)
const router = useRouter()
const userStore = useUserStore()

const registerFormData = ref({
  name: '',
  password: '',
  password_confirmation: '',
})

async function handleRegister() {
  // 表单校验
  await form$.value.validate()
  if (form$.value.invalid) {
    return
  }

  // 组装form
  const registerAPIData = {
    name: registerFormData.value.name,
    password: registerFormData.value.password,
  }

  try {
    const res = await registerAPI(registerAPIData)
    userStore.name = res.data.name
    userStore.token = res.data.token

    // 注册后直接登录
    try {
      const res = await loginAPI({
        name: registerFormData.value.name,
        password: registerFormData.value.password,
      })
      if (res.code === 1) {
        userStore.name = res.data.name
        userStore.image = res.data.image
        userStore.token = res.data.token

        // 跳转到对话
        router.replace('/')
      }
    } catch (err) {
      if (err?.code === 0) {
        alert('密码错误')
      } else {
        alert(err?.msg || '登录失败，请稍后再试')
      }
    }
  } catch (err) {
    alert(err?.msg || '注册失败，请稍后再试')
    return
  }
}
</script>

<template>
  <Vueform validate-on="change" :display-errors="false" size="lg" v-model="registerFormData" ref="form$">
    <StaticElement name="head" :loading="true">
      <h2>注册</h2>
    </StaticElement>

    <TextElement name="name" size="lg" placeholder="请输入用户名" rules="required|min:3|max:20" :debounce="300" :messages="{
      required: '用户名不能为空',
      min: '用户名至少为3个字符',
      max: '用户名至多为20个字符',
    }">
      <template #addon-before>
        <UserSVG size="20" color="#64748b"></UserSVG>
      </template>
    </TextElement>

    <TextElement name="password" input-type="password" placeholder="请输入密码" rules="required|min:6|confirmed"
      :debounce="300" :messages="{
        required: '密码不能为空',
        min: '密码至少为6个字符',
        confirmed: '两次密码不一致',
      }">
      <template #addon-before>
        <PasswordSVG size="24" color="#64748b"></PasswordSVG>
      </template>
    </TextElement>

    <TextElement name="password_confirmation" input-type="password" placeholder="请再次确认密码" rules="required"
      :debounce="300" :messages="{
        required: '确认密码不能为空',
      }">
      <template #addon-before>
        <PasswordSVG size="24" color="#64748b"></PasswordSVG>
      </template>
    </TextElement>

    <ButtonElement name="submit" @click="handleRegister" full> 注册 </ButtonElement>
  </Vueform>
</template>

<style scoped lang="scss">
h2 {
  color: #1e293b;
  margin-bottom: 1.5rem;
}

.preview img {
  width: 120px;
  height: 120px;
  object-fit: cover;
  border-radius: 50%;
}
</style>
