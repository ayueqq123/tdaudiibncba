import type { RouteRecordRaw } from 'vue-router';

import { $t } from '#/locales';

const routes: RouteRecordRaw[] = [
  {
    name: 'Tg',
    path: '/tg',
    meta: {
      title: $t('tg.title'),
      icon: 'lucide:send',
      order: 2,
    },
    children: [
      {
        name: 'TgTenant',
        path: '/tg/tenant',
        component: () => import('#/views/tg/tenant/index.vue'),
        meta: {
          title: $t('tg.tenant'),
          icon: 'lucide:building-2',
          authority: ['super'],
        },
      },
      {
        name: 'TgProject',
        path: '/tg/project',
        component: () => import('#/views/tg/project/index.vue'),
        meta: {
          title: $t('tg.project'),
          icon: 'lucide:folder',
        },
      },
      {
        name: 'TgAccount',
        path: '/tg/account',
        component: () => import('#/views/tg/account/index.vue'),
        meta: {
          title: $t('tg.account'),
          icon: 'lucide:user-round',
        },
      },
      {
        name: 'TgImport',
        path: '/tg/import',
        component: () => import('#/views/tg/import/index.vue'),
        meta: {
          title: $t('tg.import'),
          icon: 'lucide:upload',
        },
      },
      {
        name: 'TgRule',
        path: '/tg/rule',
        component: () => import('#/views/tg/rule/index.vue'),
        meta: {
          title: $t('tg.rule'),
          icon: 'lucide:git-branch',
        },
      },
      {
        name: 'TgDelivery',
        path: '/tg/delivery',
        component: () => import('#/views/tg/delivery/index.vue'),
        meta: {
          title: $t('tg.delivery'),
          icon: 'lucide:truck',
        },
      },
      {
        name: 'TgApproval',
        path: '/tg/approval',
        component: () => import('#/views/tg/approval/index.vue'),
        meta: {
          title: $t('tg.approval'),
          icon: 'lucide:shield-check',
        },
      },
      {
        name: 'TgCommand',
        path: '/tg/command',
        component: () => import('#/views/tg/command/index.vue'),
        meta: {
          title: $t('tg.command'),
          icon: 'lucide:terminal',
        },
      },
    ],
  },
];

export default routes;
