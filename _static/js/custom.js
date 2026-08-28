function reveal() {
  var classes = [".reveal_l", ".reveal_r"];
  classes.map(function (c) {
    var reveals = document.querySelectorAll(c);
    for (var i = 0; i < reveals.length; i++) {
      var windowHeight = window.innerHeight;
      var elementTop = reveals[i].getBoundingClientRect().top;
      var elementVisible = 150;
      if (elementTop < windowHeight - elementVisible) {
        reveals[i].classList.add("active");
      } else {
        reveals[i].classList.remove("active");
      }
    }
  });
}
window.addEventListener("scroll", reveal);
// To check the scroll position on page load
reveal();
