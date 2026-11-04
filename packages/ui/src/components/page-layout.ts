/**
 * Page layout contract of the admin shell. Pages render inside `.page`
 * (padding 24/32/48, max 1320 px). A page whose root element (a direct child
 * of `.page`) carries these props is full-bleed instead, as the prototype's
 * list pages are: its content touches the rail, the topbar and the right
 * edge, and it insets its own parts. ListView sets it on its root.
 */
export const fullBleedPage = { "data-page-layout": "full-bleed" } as const;
