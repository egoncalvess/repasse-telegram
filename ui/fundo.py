"""
Trabalho pesado (rede, banco) fora da thread da interface. O resultado é recolhido pela própria thread da
interface (after), então a thread de trabalho nunca toca no Tk.
"""
import threading


def em_segundo_plano(widget, trabalho, ao_terminar, intervalo_ms: int = 50):
    """Roda trabalho() numa thread; ao_terminar(resultado, erro) roda na thread da interface."""
    caixa: list = []

    def _rodar():
        try:
            caixa.append((trabalho(), None))
        except Exception as ex:  # o erro vai para a tela, que decide como mostrar
            caixa.append((None, ex))

    def _conferir():
        if not widget.winfo_exists():
            return
        if caixa:
            ao_terminar(*caixa[0])
        else:
            widget.after(intervalo_ms, _conferir)

    threading.Thread(target=_rodar, daemon=True).start()
    widget.after(intervalo_ms, _conferir)
