# Este ambiente de build roda em sandbox sem suporte a user namespaces sem
# privilegio. O bitbake tenta isolar rede via unshare (bb.utils.disable_network)
# em toda task que nao tenha a varflag [network]=1, o que falha aqui com
# "PermissionError: Operation not permitted" em /proc/self/uid_map. Nenhuma
# task deste projeto precisa de acesso real a rede (fontes sao locais/xsa
# gerado), entao marcamos as tasks padrao como "network"=1 globalmente para
# so pular essa tentativa de isolamento, nao para liberar rede de verdade.
#
# So aplicado neste ambiente (INHERIT via project-spec/meta-user/conf/petalinuxbsp.conf);
# nao afeta a semantica de build normal em um host sem essa restricao.
# Usa um handler de RecipeParsed (dispara depois que a receita — incluindo
# addtask de tasks customizadas, tipo do_copy_shared_src do fsbl-firmware —
# terminou de ser parseada), em vez de um python() anonimo, cuja ordem de
# execucao em relacao a addtask's tardios nao e garantida.
addhandler sandbox_no_netns_eh
sandbox_no_netns_eh[eventmask] = "bb.event.RecipeParsed"
python sandbox_no_netns_eh() {
    d = e.data
    for task in d.getVar('__BBTASKS', False) or []:
        if d.getVarFlag(task, 'network') is None:
            d.setVarFlag(task, 'network', '1')
}
