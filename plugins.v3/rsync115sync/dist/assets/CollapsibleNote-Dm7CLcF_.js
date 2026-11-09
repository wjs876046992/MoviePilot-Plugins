import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,withModifiers:_withModifiers,withKeys:_withKeys,renderSlot:_renderSlot,vShow:_vShow,withDirectives:_withDirectives,createBlock:_createBlock} = await importShared('vue');


const _hoisted_1 = ["aria-expanded", "onKeydown"];
const _hoisted_2 = { class: "font-weight-bold" };
const _hoisted_3 = {
  key: 0,
  class: "text-medium-emphasis note-hint"
};
const _hoisted_4 = { class: "mt-1" };

const {ref} = await importShared('vue');



const _sfc_main = {
  __name: 'CollapsibleNote',
  props: {
  title: { type: String, required: true },
},
  setup(__props) {



const open = ref(false);
function toggle() { open.value = !open.value; }

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_alert = _resolveComponent("v-alert");

  return (_openBlock(), _createBlock(_component_v_alert, {
    type: "info",
    variant: "tonal",
    density: "compact",
    icon: false,
    class: "radius-sm text-body-2 collapsible-note"
  }, {
    default: _withCtx(() => [
      _createElementVNode("div", {
        class: "note-head d-flex align-center",
        role: "button",
        tabindex: "0",
        "aria-expanded": open.value ? 'true' : 'false',
        onClick: toggle,
        onKeydown: [
          _withKeys(_withModifiers(toggle, ["prevent"]), ["enter"]),
          _withKeys(_withModifiers(toggle, ["prevent"]), ["space"])
        ]
      }, [
        _createVNode(_component_v_icon, {
          size: "16",
          class: "mr-1 flex-shrink-0"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(open.value ? 'mdi-chevron-up' : 'mdi-chevron-down'), 1)
          ]),
          _: 1
        }),
        _createElementVNode("span", _hoisted_2, _toDisplayString(__props.title), 1),
        (!open.value)
          ? (_openBlock(), _createElementBlock("span", _hoisted_3, "（点击展开）"))
          : _createCommentVNode("", true)
      ], 40, _hoisted_1),
      _withDirectives(_createElementVNode("div", _hoisted_4, [
        _renderSlot(_ctx.$slots, "default", {}, undefined, true)
      ], 512), [
        [_vShow, open.value]
      ])
    ]),
    _: 3
  }))
}
}

};
const CollapsibleNote = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-b0f1714d"]]);

export { CollapsibleNote as C, _export_sfc as _ };
